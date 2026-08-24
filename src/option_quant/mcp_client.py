# -*- coding: utf-8 -*-
"""
Robinhood MCP Bridge Client
===========================
Robust, high-level context manager and client for interfacing with Robinhood
Model Context Protocol (MCP) server via JSON-RPC 2.0.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from option_quant.config import (
    ROBINHOOD_ACCOUNT_ID,
    get_robinhood_account_id,
    mask_account_id,
    normalize_symbol,
    to_rh_symbol,
)

logger = logging.getLogger("option_quant.mcp_client")


class RobinhoodMCPClient:
    """
    Client for managing the Robinhood MCP connection over standard I/O pipes.
    Provides automated JSON-RPC handshake, message parsing, cursor pagination,
    exponential retries, and high-level trading/portfolio queries.
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        remote_url: str = "https://agent.robinhood.com/mcp/trading",
        request_timeout: float = 30.0,
    ):
        self.account_id = account_id or get_robinhood_account_id() or ROBINHOOD_ACCOUNT_ID
        self.remote_url = remote_url
        self.request_timeout = request_timeout
        self.proc: Optional[subprocess.Popen] = None
        self._req_id = 1

    def __enter__(self) -> RobinhoodMCPClient:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @staticmethod
    def _ensure_auth_tokens_synced() -> None:
        """
        Ensure OAuth tokens and client_info are copied to any newly created or existing
        mcp-remote version directories under ~/.mcp-auth to prevent browser re-auth prompts
        when mcp-remote package version updates.
        """
        import glob
        import shutil

        auth_base = os.path.expanduser("~/.mcp-auth")
        if not os.path.exists(auth_base):
            return

        dirs = [
            os.path.join(auth_base, d)
            for d in os.listdir(auth_base)
            if os.path.isdir(os.path.join(auth_base, d)) and d.startswith("mcp-remote")
        ]
        if not dirs:
            return

        # Find the directory with the most recently modified tokens
        latest_dir = None
        latest_mtime = 0.0
        for d in dirs:
            tf = glob.glob(os.path.join(d, "*_tokens.json"))
            if tf:
                mt = os.path.getmtime(tf[0])
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_dir = d

        if not latest_dir:
            return

        # Sync latest tokens and client_info across all other mcp-remote directories
        for d in dirs:
            if d != latest_dir:
                for f in glob.glob(os.path.join(latest_dir, "*.*")):
                    fname = os.path.basename(f)
                    if fname.endswith("_tokens.json") or fname.endswith("_client_info.json"):
                        target_file = os.path.join(d, fname)
                        try:
                            shutil.copy2(f, target_file)
                        except Exception:
                            pass

    def start(self) -> None:
        """Start the MCP subprocess and complete the handshake."""
        self._ensure_auth_tokens_synced()
        cmd = ["npx", "-y", "mcp-remote@0.2.1", self.remote_url]
        logger.info(f"Launching Robinhood MCP bridge: {' '.join(cmd)}")
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        # 1. Initialize Handshake
        init_req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "the-sell-put-king-client", "version": "1.0.0"},
            },
        }
        self._write_msg(init_req)
        raw_res = self._read_msg(init_req["id"])
        logger.debug(f"MCP handshake response: {raw_res}")

        # 2. Initialized Notification
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        self._write_msg(notif)
        logger.info(f"Robinhood MCP initialized successfully (Account: {mask_account_id(self.account_id)}).")

    def close(self) -> None:
        """Terminate the MCP bridge subprocess cleanly."""
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            finally:
                self.proc = None
                logger.info("Robinhood MCP bridge terminated cleanly.")

    def _next_id(self) -> int:
        cur = self._req_id
        self._req_id += 1
        return cur

    def _write_msg(self, msg: Dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("MCP process is not running.")
        line = json.dumps(msg) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def _read_msg(self, expected_id: Optional[int] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if not self.proc or not self.proc.stdout:
            raise RuntimeError("MCP process is not running.")

        start_time = time.time()
        max_wait = timeout or self.request_timeout

        while True:
            if time.time() - start_time > max_wait:
                logger.warning(f"Timeout ({max_wait}s) waiting for response with id={expected_id}")
                return None

            line = self.proc.stdout.readline()
            if not line:
                return None

            line_str = line.strip()
            if not line_str:
                continue

            try:
                res = json.loads(line_str)
                if expected_id is None or res.get("id") == expected_id:
                    return res
            except json.JSONDecodeError:
                continue

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        max_retries: int = 3,
        retry_delay: float = 1.5,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute an MCP tool call with exponential retries for transient upstream errors.

        Args:
            tool_name: Name of the MCP tool.
            arguments: Tool arguments dictionary.
            max_retries: Maximum attempts.
            retry_delay: Delay between retries.

        Returns:
            Extracted JSON dictionary or None on failure.
        """
        for attempt in range(1, max_retries + 1):
            req_id = self._next_id()
            req = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }
            self._write_msg(req)
            res = self._read_msg(req_id)

            if not res:
                logger.warning(f"No response for {tool_name} (attempt {attempt}/{max_retries})")
                time.sleep(retry_delay * attempt)
                continue

            if "error" in res:
                err_msg = str(res["error"])
                logger.warning(f"MCP error on {tool_name}: {err_msg} (attempt {attempt}/{max_retries})")
                if "503" in err_msg or "deadline" in err_msg.lower():
                    time.sleep(retry_delay * attempt)
                    continue
                return None

            # Parse content text payload
            content = res.get("result", {}).get("content", [])
            for item in content:
                if item.get("type") == "text":
                    text_val = item.get("text", "{}")
                    try:
                        parsed = json.loads(text_val)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        return {"raw_text": text_val}

            result_obj = res.get("result")
            if isinstance(result_obj, dict):
                return result_obj

        return None

    # ==================== HIGH LEVEL API METHODS ====================

    def get_portfolio(self, account_number: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch account portfolio balance and unleveraged buying power."""
        acc = account_number or self.account_id
        return self.call_tool("get_portfolio", {"account_number": acc})

    def get_equity_positions(self, account_number: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch all equity stock holdings."""
        acc = account_number or self.account_id
        return self.call_tool("get_equity_positions", {"account_number": acc})

    def get_option_positions(self, account_number: Optional[str] = None, nonzero: bool = True) -> Optional[Dict[str, Any]]:
        """Fetch active non-zero option contracts."""
        acc = account_number or self.account_id
        return self.call_tool("get_option_positions", {"account_number": acc, "nonzero": nonzero})

    def get_pnl_trade_history(self, account_number: Optional[str] = None, span: str = "month") -> List[Dict[str, Any]]:
        """Fetch realized PnL trade history for Wash Sale checks."""
        acc = account_number or self.account_id
        res = self.call_tool("get_pnl_trade_history", {"account_number": acc, "span": span})
        if res and isinstance(res.get("data"), dict):
            return res["data"].get("trades", [])
        return []

    def get_option_instruments(
        self,
        chain_symbol: Optional[str] = None,
        expiration_dates: Optional[List[str]] = None,
        opt_type: Optional[str] = None,
        ids: Optional[List[str]] = None,
        state: str = "active",
    ) -> List[Dict[str, Any]]:
        """
        Fetch option instruments with automatic cursor pagination handling.
        """
        if ids:
            res = self.call_tool("get_option_instruments", {"ids": ",".join(ids)})
            if res and isinstance(res.get("data"), dict):
                return res["data"].get("instruments", [])
            return []

        if not chain_symbol or not expiration_dates or not opt_type:
            return []

        all_instruments: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        rh_chain = to_rh_symbol(chain_symbol)

        while True:
            args: Dict[str, Any] = {
                "chain_symbol": rh_chain,
                "expiration_dates": ",".join(expiration_dates) if isinstance(expiration_dates, list) else str(expiration_dates),
                "type": opt_type,
                "state": state,
            }
            if cursor:
                args["cursor"] = cursor

            res = self.call_tool("get_option_instruments", args)
            if not res or not isinstance(res.get("data"), dict):
                break

            data_obj = res["data"]
            insts = data_obj.get("instruments", [])
            all_instruments.extend(insts)

            next_url = data_obj.get("next")
            if not next_url:
                break

            parsed = urlparse(next_url)
            qs = parse_qs(parsed.query)
            cursor_list = qs.get("cursor")
            if cursor_list:
                cursor = cursor_list[0]
            else:
                break

        return all_instruments

    def get_option_quotes(self, instrument_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch quotes for a list of option instrument IDs."""
        if not instrument_ids:
            return []
        res = self.call_tool("get_option_quotes", {"instrument_ids": instrument_ids})
        if not res:
            return []
        data_obj = res.get("data", {})
        if isinstance(data_obj, dict):
            results = data_obj.get("results", [])
            quotes = []
            for item in results:
                q = item.get("quote")
                if q:
                    quotes.append(q)
            return quotes
        return []

    def get_watchlists(self) -> List[Dict[str, Any]]:
        """Fetch all user watchlists."""
        res = self.call_tool("get_watchlists", {})
        if not res:
            return []
        data = res.get("data", {})
        if isinstance(data, dict):
            return data.get("watchlists", [])
        elif isinstance(data, list):
            return data
        return res.get("watchlists", [])

    def create_watchlist(self, display_name: str) -> Optional[str]:
        """Create a new watchlist and return its ID."""
        res = self.call_tool("create_watchlist", {"display_name": display_name})
        if res and "data" in res:
            return res["data"].get("id")
        return None

    def get_watchlist_items(self, list_id: str) -> List[str]:
        """Get all stock symbols in a watchlist."""
        res = self.call_tool("get_watchlist_items", {"list_id": list_id})
        if not res:
            return []
        data = res.get("data", {})
        items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else res.get("items", []))
        symbols = []
        for it in items:
            if isinstance(it, dict) and it.get("symbol"):
                symbols.append(it["symbol"])
        return symbols

    def remove_from_watchlist(self, list_id: str, symbols: List[str]) -> bool:
        """Remove symbols from a watchlist."""
        if not symbols:
            return True
        res = self.call_tool("remove_from_watchlist", {"list_id": list_id, "symbols": symbols})
        return res is not None

    def add_to_watchlist(self, list_id: str, symbols: List[str]) -> bool:
        """Add symbols to a watchlist."""
        if not symbols:
            return True
        res = self.call_tool("add_to_watchlist", {"list_id": list_id, "symbols": symbols})
        return res is not None
