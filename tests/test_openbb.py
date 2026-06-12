"""Manual OpenBB connectivity probe — NOT a unit test (live network, no assertions).
Run directly: `python tests/test_openbb.py`. Skipped under pytest by the marker below."""
import sys
import asyncio
import traceback

import pytest

pytestmark = pytest.mark.skip(reason="manual live-network probe (openbb/FRED/yfinance) — run directly")


async def test():
    try:
        from openbb import obb
        print("OpenBB imported successfully.")
        
        # Test FRED series
        print("Testing FRED DCOILWTICO...")
        res = obb.economy.fred_series("DCOILWTICO")
        print("WTI:", res.to_dataframe().iloc[-1])
        
        # Test Equity Fundamental (Sloan ratio components)
        print("Testing Equity Fundamentals for GROY...")
        # Since standard openbb might use different providers (yfinance, fmp), we'll try default.
        res_cf = obb.equity.fundamental.cash("GROY", provider="yfinance")
        res_bs = obb.equity.fundamental.balance("GROY", provider="yfinance")
        res_inc = obb.equity.fundamental.income("GROY", provider="yfinance")
        print("Cash Flow:", res_cf.to_dataframe().columns if not res_cf.to_dataframe().empty else "Empty")
        
        # Test Futures Curve
        print("Testing Futures Curve for SI...")
        try:
            res_curve = obb.derivatives.futures.curve("SI")
            print("Curve:", res_curve.to_dataframe().head())
        except Exception as e:
            print("Curve error:", e)
            
    except Exception as e:
        print("Error:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
