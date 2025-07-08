import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timezone
import json # <-- برای ذخیره فایل جیسون
import config

# تمام توابع تحلیلی که داشتیم اینجا هم کپی می‌شوند
def calculate_heikin_ashi(df):
    ha_close = (df['Open'] + df['High'] + df['Low'] + df['Close']) / 4
    ha_open = pd.Series(0.0, index=df.index)
    ha_open.iloc[0] = (df['Open'].iloc[0] + df['Close'].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i-1] + ha_close.iloc[i-1]) / 2
    ha_high = pd.DataFrame({'High': df['High'], 'HA_Open': ha_open, 'HA_Close': ha_close}).max(axis=1)
    ha_low = pd.DataFrame({'Low': df['Low'], 'HA_Open': ha_open, 'HA_Close': ha_close}).min(axis=1)
    return pd.DataFrame({'HA_Open': ha_open, 'HA_High': ha_high, 'HA_Low': ha_low, 'HA_Close': ha_close})

def calculate_atr(df, period):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift(1))
    low_close = np.abs(df['Low'] - df['Close'].shift(1))
    tr = pd.DataFrame({'HL': high_low, 'HC': high_close, 'LC': low_close}).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def future_monster_indicator(df, key_value, atr_period, use_heikin_ashi):
    df_copy = df.copy()
    if use_heikin_ashi:
        ha_df = calculate_heikin_ashi(df_copy)
        df_for_atr = ha_df.rename(columns={'HA_High': 'High', 'HA_Low': 'Low', 'HA_Close': 'Close'})
        src = ha_df['HA_Close']
    else:
        df_for_atr = df_copy
        src = df_copy['Close']
    df_copy['xATR'] = calculate_atr(df_for_atr, atr_period)
    df_copy['nLoss'] = key_value * df_copy['xATR']
    xATRTrailingStop = pd.Series(0.0, index=df_copy.index)
    pos = pd.Series(0, index=df_copy.index)
    for i in range(len(df_copy)):
        current_src = src.iloc[i]
        current_nLoss = df_copy['nLoss'].iloc[i]
        if i == 0:
            xATRTrailingStop.iloc[i] = current_src - current_nLoss
            pos.iloc[i] = 1
        else:
            prev_xATRTrailingStop_val = xATRTrailingStop.iloc[i-1]
            prev_src_val = src.iloc[i-1]
            prev_pos_val = pos.iloc[i-1]
            if current_src > prev_xATRTrailingStop_val and prev_src_val > prev_xATRTrailingStop_val:
                xATRTrailingStop.iloc[i] = max(prev_xATRTrailingStop_val, current_src - current_nLoss)
            elif current_src < prev_xATRTrailingStop_val and prev_src_val < prev_xATRTrailingStop_val:
                xATRTrailingStop.iloc[i] = min(prev_xATRTrailingStop_val, current_src + current_nLoss)
            elif current_src > prev_xATRTrailingStop_val:
                xATRTrailingStop.iloc[i] = current_src - current_nLoss
            else:
                xATRTrailingStop.iloc[i] = current_src + current_nLoss
            if prev_src_val < prev_xATRTrailingStop_val and current_src > prev_xATRTrailingStop_val:
                pos.iloc[i] = 1
            elif prev_src_val > prev_xATRTrailingStop_val and current_src < prev_xATRTrailingStop_val:
                pos.iloc[i] = -1
            else:
                pos.iloc[i] = prev_pos_val
    df_copy['xATRTrailingStop'] = xATRTrailingStop
    df_copy['pos'] = pos
    df_copy['ema'] = calculate_ema(src, 1)
    df_copy['above'] = (df_copy['ema'].shift(1) < df_copy['xATRTrailingStop'].shift(1)) & (df_copy['ema'] > df_copy['xATRTrailingStop'])
    df_copy['below'] = (df_copy['xATRTrailingStop'].shift(1) < df_copy['ema'].shift(1)) & (df_copy['xATRTrailingStop'] > df_copy['ema'])
    df_copy['buy_signal'] = (src > df_copy['xATRTrailingStop']) & df_copy['above']
    df_copy['sell_signal'] = (src < df_copy['xATRTrailingStop']) & df_copy['below']
    return df_copy
    
def get_wallex_markets():
    url = "https://api.wallex.ir/v1/markets"
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        data = response.json()
        symbols = list(data['result']['symbols'].keys())
        return [s for s in symbols if (s.endswith("TMN") or s.endswith("USDT")) and len(s) >= 5 and s.isupper()]
    except Exception as e:
        print(f"Error fetching markets: {e}")
        return []

def get_wallex_candles(symbol, resolution, from_time, to_time):
    base_url = "https://api.wallex.ir/v1/udf/history"
    params = {"symbol": symbol, "resolution": resolution, "from": from_time, "to": to_time}
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get('s') == 'ok' and all(key in data and data[key] for key in ['t', 'o', 'h', 'l', 'c']):
            return pd.DataFrame({
                'Time': pd.to_datetime(data['t'], unit='s'),
                'Open': [float(o) for o in data['o']], 'High': [float(h) for h in data['h']],
                'Low': [float(l) for l in data['l']], 'Close': [float(c) for c in data['c']]
            }).set_index('Time')
        return None
    except requests.exceptions.RequestException as e:
        print(f"API ERROR for {symbol}: {e}")
        return None

def run_analysis_and_save():
    """تحلیل را اجرا کرده و نتیجه را در فایل signals.json ذخیره می‌کند"""
    print(f"Worker starting analysis at {datetime.now(timezone.utc)}")
    
    # می‌توانید اینجا از لیست کامل ارزها استفاده کنید چون این اسکریپت به صورت مستقل اجرا می‌شود
    all_symbols = get_wallex_markets()
    if not all_symbols:
        print("Could not get symbols. Exiting.")
        return

    print(f"Found {len(all_symbols)} symbols. Starting analysis...")
    signals_found = []

    for symbol in all_symbols:
        time.sleep(0.5) # برای جلوگیری از بلاک شدن توسط API
        df_wallex = get_wallex_candles(symbol, config.RESOLUTION_TO_USE, config.START_TIME, config.END_TIME)
        if df_wallex is None or df_wallex.empty or len(df_wallex) < config.ATR_PERIOD + 2:
            continue

        results_df = future_monster_indicator(df_wallex.copy(), config.KEY_VALUE, config.ATR_PERIOD, config.USE_HEIKIN_ASHI)
        last_candle = results_df.iloc[-1]
        signal_type = 'BUY' if last_candle['buy_signal'] else 'SELL' if last_candle['sell_signal'] else None

        if signal_type:
            signal_data = {
                "symbol": symbol, "signal_type": signal_type, "price": f"{last_candle['Close']:.8f}",
                "timeframe_minutes": config.RESOLUTION_TO_USE, "timestamp_utc": datetime.now(timezone.utc).isoformat()
            }
            signals_found.append(signal_data)
            print(f"-> Signal found for {symbol}: {signal_type}")

    # ساخت دیکشنری نهایی برای ذخیره
    output_data = {
        "status": "success",
        "signal_count": len(signals_found),
        "data": signals_found,
        "last_updated_utc": datetime.now(timezone.utc).isoformat()
    }

    # ذخیره خروجی در فایل جیسون
    with open('signals.json', 'w') as f:
        json.dump(output_data, f, indent=4)
        
    print(f"Analysis finished. Results saved to signals.json. Found {len(signals_found)} signals.")

if __name__ == "__main__":
    run_analysis_and_save()
