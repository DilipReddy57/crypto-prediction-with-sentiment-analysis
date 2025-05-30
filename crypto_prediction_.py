# -*- coding: utf-8 -*-
"""crypto prediction .ipynb


!pip install pycoingecko
from pycoingecko import CoinGeckoAPI

#!/usr/bin/env python
# coding: utf-8

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout, Bidirectional
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
from datetime import datetime, timedelta
import time
import ipywidgets as widgets
from IPython.display import display, clear_output
import os
import requests
import warnings
import json
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error
import yfinance as yf
import ta
from newsapi import NewsApiClient
import re
from textblob import TextBlob
import concurrent.futures

# Suppress specific warnings
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=UserWarning, module='statsmodels')

# Constants
MODEL_VERSION = "2.0"
DEFAULT_API_KEY = "YOUR_API_KEY"  # Replace with your actual API key
NEWS_API_KEY = "9b9c916fbd2e444d8e70561f567bbe10"  # Replace with your NewsAPI key

# Fetch USD to INR exchange rate with improved error handling
def get_usd_to_inr():
    try:
        response = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return data["rates"].get("INR", 83.0)
        else:
            print(f"Exchange rate API returned status code: {response.status_code}")
            return 83.0
    except Exception as e:
        print(f"Error fetching exchange rate: {e}")
        return 83.0

# Search for a cryptocurrency by name or symbol
def search_cryptocurrency(query):
    """Search for a cryptocurrency by name or symbol using CoinGecko API"""
    try:
        print(f"Searching for cryptocurrency: {query}")
        url = "https://api.coingecko.com/api/v3/search"
        params = {'query': query}

        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"Error searching cryptocurrencies. Status code: {response.status_code}")
            return None

        data = response.json()
        coins = data.get('coins', [])

        if not coins:
            print(f"No cryptocurrencies found matching '{query}'")
            return None

        # Return the top 5 results
        top_results = []
        for i, coin in enumerate(coins[:5]):
            top_results.append({
                'id': coin['id'],
                'symbol': coin['symbol'].upper(),
                'name': coin['name'],
                'market_cap_rank': coin.get('market_cap_rank', 'N/A')
            })

        return top_results

    except Exception as e:
        print(f"Error searching cryptocurrency: {e}")
        return None

# Fetch crypto data from CoinGecko API with improved reliability
def fetch_crypto_data(coin_id, days=365):
    """Fetch historical cryptocurrency data from CoinGecko API"""
    try:
        print(f"Fetching {days} days of data for {coin_id}...")
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        params = {
            'vs_currency': 'usd',
            'days': days,
            'interval': 'daily'
        }

        # Add a delay to avoid rate limiting
        time.sleep(1)

        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"Error fetching data. Status code: {response.status_code}")
            if response.text:
                print(f"Response: {response.text[:300]}...")  # Print first 300 chars to avoid flooding output

            # Try with fewer days if we got a 429 (rate limit) or 401
            if (response.status_code == 429 or response.status_code == 401) and days > 90:
                print("Rate limit reached. Trying with fewer days...")
                time.sleep(2)  # Wait longer before retry
                return fetch_crypto_data(coin_id, days=90)

            return None

        data = response.json()

        # CoinGecko returns timestamp in milliseconds and price as [timestamp, price] pairs
        prices = data.get('prices', [])
        volumes = data.get('total_volumes', [])
        market_caps = data.get('market_caps', [])

        if not prices:
            return None

        # Convert to DataFrame
        df = pd.DataFrame(prices, columns=['timestamp', 'price'])
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('date', inplace=True)
        df.drop('timestamp', axis=1, inplace=True)
        df.rename(columns={'price': 'Close'}, inplace=True)

        # Add volume and market cap data
        if volumes:
            vol_df = pd.DataFrame(volumes, columns=['timestamp', 'volume'])
            vol_df['date'] = pd.to_datetime(vol_df['timestamp'], unit='ms')
            vol_df.set_index('date', inplace=True)
            df['Volume'] = vol_df['volume']

        if market_caps:
            cap_df = pd.DataFrame(market_caps, columns=['timestamp', 'market_cap'])
            cap_df['date'] = pd.to_datetime(cap_df['timestamp'], unit='ms')
            cap_df.set_index('date', inplace=True)
            df['MarketCap'] = cap_df['market_cap']

        # Add estimated OHLC data
        df['Open'] = df['Close'].shift(1)
        df['High'] = df['Close'] * (1 + np.random.uniform(0, 0.01, size=len(df)))
        df['Low'] = df['Close'] * (1 - np.random.uniform(0, 0.01, size=len(df)))

        # Fill NaN values in first row
        if len(df) > 0:
            df.iloc[0, df.columns.get_indexer(['Open'])] = df.iloc[0]['Close']
            df.iloc[0, df.columns.get_indexer(['High'])] = df.iloc[0]['Close'] * 1.01
            df.iloc[0, df.columns.get_indexer(['Low'])] = df.iloc[0]['Close'] * 0.99

        print(f"Successfully fetched {len(df)} days of data")
        return df

    except Exception as e:
        print(f"Error fetching crypto data: {e}")
        return None

# Fetch data from multiple sources with failover options
def fetch_crypto_data_multi_source(symbol, coin_id=None):
    """Try multiple sources to fetch cryptocurrency data"""
    if coin_id is None:
        # Try to find the coin_id if not provided
        search_results = search_cryptocurrency(symbol.split('-')[0] if '-' in symbol else symbol)
        if search_results and len(search_results) > 0:
            coin_id = search_results[0]['id']
            print(f"Found coin ID: {coin_id} for {symbol}")
        else:
            print(f"Could not find CoinGecko ID for {symbol}")

    # Try CoinGecko first if we have a coin_id
    if coin_id:
        data = fetch_crypto_data(coin_id, days=365)
        if data is not None and not data.empty:
            return data, coin_id

    # Try yfinance
    print(f"Trying to fetch {symbol} data from Yahoo Finance...")
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1y")
        if data is not None and not data.empty:
            # Make sure data has the expected columns
            required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            missing_cols = [col for col in required_cols if col not in data.columns]

            if missing_cols:
                print(f"Warning: Missing columns in yfinance data: {missing_cols}")
                # Add missing columns with estimated values
                if 'Close' in data.columns:
                    for col in missing_cols:
                        if col == 'Volume':
                            data[col] = np.random.uniform(1000000, 10000000, size=len(data))
                        else:
                            # Estimate OHLC based on Close
                            if col == 'Open':
                                data[col] = data['Close'].shift(1)
                            elif col == 'High':
                                data[col] = data['Close'] * 1.01
                            elif col == 'Low':
                                data[col] = data['Close'] * 0.99

            print(f"Successfully fetched {len(data)} days of data from Yahoo Finance")
            return data, symbol
    except Exception as e:
        print(f"Error fetching from Yahoo Finance: {e}")

    # Try CryptoCompare as last resort
    print(f"Trying to fetch data from CryptoCompare...")
    base_currency = symbol.split('-')[0] if '-' in symbol else symbol

    try:
        url = "https://min-api.cryptocompare.com/data/v2/histoday"
        params = {
            'fsym': base_currency,
            'tsym': 'USD',
            'limit': 365,
        }

        response = requests.get(url, params=params, timeout=15)

        if response.status_code == 200:
            data = response.json()
            history = data.get('Data', {}).get('Data', [])

            if history:
                df = pd.DataFrame(history)
                df['date'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('date', inplace=True)

                # Rename columns to match expected format
                df.rename(columns={
                    'open': 'Open',
                    'high': 'High',
                    'low': 'Low',
                    'close': 'Close',
                    'volumefrom': 'Volume'
                }, inplace=True)

                # Keep only required columns
                keep_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
                available_cols = [col for col in keep_cols if col in df.columns]
                df = df[available_cols]

                # Add any missing columns
                for col in keep_cols:
                    if col not in df.columns:
                        if col == 'Volume':
                            df[col] = np.random.uniform(1000000, 10000000, size=len(df))
                        else:
                            # Estimate OHLC based on Close
                            if col == 'Open':
                                df[col] = df['Close'].shift(1)
                            elif col == 'High':
                                df[col] = df['Close'] * 1.01
                            elif col == 'Low':
                                df[col] = df['Close'] * 0.99

                print(f"Successfully fetched {len(df)} days of data from CryptoCompare")
                return df, base_currency
    except Exception as e:
        print(f"Error fetching from CryptoCompare: {e}")

    # If all methods fail
    print("Failed to fetch cryptocurrency data from all sources")
    return None, None

# Fetch external market factors that affect crypto
def fetch_market_factors():
    """Fetch relevant market factors that influence cryptocurrency prices"""
    try:
        # Create a dictionary to store all market factors
        market_factors = {}

        # 1. Fetch S&P 500 data as a proxy for overall market sentiment
        print("Fetching S&P 500 data...")
        sp500 = yf.download('^GSPC', period='1y', interval='1d')
        if not sp500.empty:
            market_factors['sp500'] = sp500['Close'].pct_change().fillna(0).values

        # 2. Fetch Bitcoin dominance as a market factor
        print("Fetching Bitcoin market dominance...")
        try:
            response = requests.get('https://api.coingecko.com/api/v3/global', timeout=10)
            if response.status_code == 200:
                data = response.json()
                btc_dominance = data.get('data', {}).get('market_cap_percentage', {}).get('btc', 50)
                market_factors['btc_dominance'] = btc_dominance
                print(f"Current BTC dominance: {btc_dominance}%")
        except Exception as e:
            print(f"Error fetching BTC dominance: {e}")

        # 3. Fetch DXY (Dollar Index) as a measure of USD strength
        print("Fetching Dollar Index (DXY) data...")
        dxy = yf.download('DX-Y.NYB', period='1y', interval='1d')
        if not dxy.empty:
            market_factors['dxy'] = dxy['Close'].pct_change().fillna(0).values

        # 4. Fetch Gold price for inflation hedge comparison
        print("Fetching Gold price data...")
        gold = yf.download('GC=F', period='1y', interval='1d')
        if not gold.empty:
            market_factors['gold'] = gold['Close'].pct_change().fillna(0).values

        # 5. Fetch VIX volatility index for market fear/greed
        print("Fetching VIX volatility data...")
        vix = yf.download('^VIX', period='1y', interval='1d')
        if not vix.empty:
            market_factors['vix'] = vix['Close'].values

        # 6. Get current fear & greed index if available
        try:
            response = requests.get('https://api.alternative.me/fng/', timeout=10)
            if response.status_code == 200:
                data = response.json()
                fg_value = data.get('data', [{}])[0].get('value', 50)
                market_factors['fear_greed'] = int(fg_value)
                print(f"Current Fear & Greed Index: {fg_value}")
        except Exception as e:
            print(f"Error fetching Fear & Greed index: {e}")

        return market_factors

    except Exception as e:
        print(f"Error fetching market factors: {e}")
        return {}

# Sentiment analysis from news
def get_crypto_sentiment(coin_name, symbol):
    """Fetch and analyze news sentiment for a cryptocurrency"""
    try:
        # Initialize sentiment scores
        sentiment_score = 0
        sentiment_magnitude = 0
        article_count = 0

        # Try to use NewsAPI if key is provided
        if NEWS_API_KEY != "YOUR_NEWS_API_KEY":
            newsapi = NewsApiClient(api_key=NEWS_API_KEY)

            # Get news about the specific cryptocurrency
            all_articles = newsapi.get_everything(
                q=f'{coin_name} OR {symbol} cryptocurrency',
                language='en',
                sort_by='publishedAt',
                page_size=10
            )

            articles = all_articles.get('articles', [])

            # Process each article
            for article in articles:
                title = article.get('title', '')
                description = article.get('description', '')

                # Combine title and description for analysis
                content = f"{title}. {description}"

                # Use TextBlob for sentiment analysis
                analysis = TextBlob(content)
                sentiment_score += analysis.sentiment.polarity
                sentiment_magnitude += abs(analysis.sentiment.polarity)
                article_count += 1

        # If no articles found or no API key, use a simpler approach
        if article_count == 0:
            # Set a neutral sentiment with slight positive bias for established coins
            sentiment_score = 0.1
            sentiment_magnitude = 0.5

        # Calculate average
        if article_count > 0:
            avg_sentiment = sentiment_score / article_count
            avg_magnitude = sentiment_magnitude / article_count
        else:
            avg_sentiment = sentiment_score
            avg_magnitude = sentiment_magnitude

        print(f"News sentiment for {coin_name}: {avg_sentiment:.2f} (magnitude: {avg_magnitude:.2f})")

        return {
            'sentiment_score': avg_sentiment,
            'sentiment_magnitude': avg_magnitude,
            'article_count': article_count
        }

    except Exception as e:
        print(f"Error getting news sentiment: {e}")
        return {
            'sentiment_score': 0.1,  # Slightly positive default
            'sentiment_magnitude': 0.5,
            'article_count': 0
        }

# Calculate advanced technical indicators
def add_technical_indicators(data):
    """Add comprehensive technical indicators to the dataframe"""
    # Make a copy to avoid SettingWithCopyWarning
    df = data.copy()

    try:
        # Volume indicators
        if 'Volume' in df.columns:
            # Money Flow Index
            df['MFI'] = ta.volume.money_flow_index(
                high=df['High'],
                low=df['Low'],
                close=df['Close'],
                volume=df['Volume'],
                window=14,
                fillna=True
            )

            # On-Balance Volume
            df['OBV'] = ta.volume.on_balance_volume(
                close=df['Close'],
                volume=df['Volume'],
                fillna=True
            )

            # Volume Weighted Average Price
            df['VWAP'] = (df['Close'] * df['Volume']).cumsum() / df['Volume'].cumsum()

        # Trend indicators
        # ADX - Average Directional Index
        df['ADX'] = ta.trend.adx(
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            window=14,
            fillna=True
        )

        # Moving averages
        for window in [5, 7, 14, 30, 50, 200]:
            df[f'SMA_{window}'] = ta.trend.sma_indicator(
                close=df['Close'],
                window=window,
                fillna=True
            )
            df[f'EMA_{window}'] = ta.trend.ema_indicator(
                close=df['Close'],
                window=window,
                fillna=True
            )

        # MACD
        df['MACD_line'] = ta.trend.macd(
            close=df['Close'],
            window_slow=26,
            window_fast=12,
            fillna=True
        )
        df['MACD_signal'] = ta.trend.macd_signal(
            close=df['Close'],
            window_slow=26,
            window_fast=12,
            window_sign=9,
            fillna=True
        )
        df['MACD_diff'] = ta.trend.macd_diff(
            close=df['Close'],
            window_slow=26,
            window_fast=12,
            window_sign=9,
            fillna=True
        )

        # Momentum indicators
        # RSI
        df['RSI'] = ta.momentum.rsi(
            close=df['Close'],
            window=14,
            fillna=True
        )

        # Stochastic Oscillator
        df['STOCH_k'] = ta.momentum.stoch(
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            window=14,
            smooth_window=3,
            fillna=True
        )
        df['STOCH_d'] = ta.momentum.stoch_signal(
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            window=14,
            smooth_window=3,
            fillna=True
        )

        # ROC - Rate of Change
        for period in [5, 14, 21]:
            df[f'ROC_{period}'] = ta.momentum.roc(
                close=df['Close'],
                window=period,
                fillna=True
            )

        # Volatility indicators
        # Bollinger Bands
        df['BB_high'] = ta.volatility.bollinger_hband(
            close=df['Close'],
            window=20,
            window_dev=2,
            fillna=True
        )
        df['BB_mid'] = ta.volatility.bollinger_mavg(
            close=df['Close'],
            window=20,
            fillna=True
        )
        df['BB_low'] = ta.volatility.bollinger_lband(
            close=df['Close'],
            window=20,
            window_dev=2,
            fillna=True
        )
        df['BB_width'] = (df['BB_high'] - df['BB_low']) / df['BB_mid']

        # ATR - Average True Range (volatility)
        df['ATR'] = ta.volatility.average_true_range(
            high=df['High'],
            low=df['Low'],
            close=df['Close'],
            window=14,
            fillna=True
        )

        # Custom indicators
        # Price distance from moving averages (%)
        df['Dist_SMA50'] = ((df['Close'] - df['SMA_50']) / df['SMA_50']) * 100
        df['Dist_SMA200'] = ((df['Close'] - df['SMA_200']) / df['SMA_200']) * 100

        # Golden Cross / Death Cross indicator
        df['MA_Cross'] = np.where(df['SMA_50'] > df['SMA_200'], 1, -1)

        # Price momentum
        df['Price_Momentum'] = df['Close'].pct_change(periods=5) * 100

        # Volatility (using simple approximation)
        df['Volatility'] = df['Close'].pct_change().rolling(window=14).std() * 100

        # Remove any remaining NaN values
        df.fillna(method='bfill', inplace=True)
        df.fillna(method='ffill', inplace=True)
        df.fillna(0, inplace=True)

        return df

    except Exception as e:
        print(f"Error calculating technical indicators: {e}")
        # Return original data if we encounter errors
        return data

# Enhanced model training with ensemble approach
def train_ensemble_model(data, features, target_col='Close', time_step=14):
    """Train an ensemble of models for more accurate prediction"""
    # Make sure we have enough data
    if len(data) < time_step * 2:
        print(f"Not enough data points ({len(data)}) for training. Need at least {time_step * 2}.")
        return None, None, None

    print("Training ensemble prediction model...")

    # Scale the data
    scaler = MinMaxScaler(feature_range=(0,1))
    data_scaled = scaler.fit_transform(data[features])

    # Create sequences for LSTM
    def create_sequences(data, time_step=14):
        X, y = [], []
        for i in range(len(data) - time_step):
            X.append(data[i:(i + time_step)])
            y.append(data[i + time_step, features.index(target_col)])  # Target is Close price
        return np.array(X), np.array(y)

    X, y = create_sequences(data_scaled, time_step)

    # Train-Test Split
    train_size = int(len(X) * 0.8)
    X_train, X_test = X[:train_size], X[train_size:]
    y_train, y_test = y[:train_size], y[train_size:]

    # 1. Build LSTM Model
    print("Training deep learning model...")
    lstm_model = Sequential([
        Bidirectional(LSTM(64, return_sequences=True, input_shape=(time_step, len(features)))),
        Dropout(0.3),
        LSTM(32, return_sequences=False),
        Dropout(0.2),
        Dense(16, activation='relu'),
        Dense(1)
    ])
    lstm_model.compile(optimizer='adam', loss='mean_squared_error')
    early_stopping = EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)

    batch_size = min(32, len(X_train) // 4)
    if batch_size < 1: batch_size = 1

    lstm_model.fit(
        X_train, y_train,
        validation_data=(X_test, y_test),
        epochs=100,
        batch_size=batch_size,
        callbacks=[early_stopping],
        verbose=1
    )

    # 2. Train Random Forest model on flattened data
    print("Training random forest model...")
    # Flatten the LSTM input for RF
    X_train_flat = X_train.reshape(X_train.shape[0], -1)  # Flatten the 3D data to 2D
    X_test_flat = X_test.reshape(X_test.shape[0], -1)

    rf_model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42)
    rf_model.fit(X_train_flat, y_train)

    return lstm_model, rf_model, scaler

# Ensemble prediction function
def make_ensemble_prediction(lstm_model, rf_model, scaler, input_data, features, time_step=14):
    """Make prediction using ensemble of models for better accuracy"""
    # Make lstm prediction
    lstm_pred = lstm_model.predict(input_data, verbose=0)

    # Flatten input data for random forest
    flat_input = input_data.reshape(input_data.shape[0], -1)
    rf_pred = rf_model.predict(flat_input).reshape(-1, 1)

    # Ensemble: Average predictions with different weights
    ensemble_pred = lstm_pred * 0.7 + rf_pred * 0.3

    # Create empty array to inverse transform
    pred_data = np.zeros((len(ensemble_pred), len(features)))
    pred_data[:, features.index('Close_INR')] = ensemble_pred.flatten()

    # Inverse transform to get actual values
    predictions = scaler.inverse_transform(pred_data)[:, features.index('Close_INR')]

    return predictions

# Market analysis and factors report
def generate_market_analysis(coin_name, symbol, sentiment_data, market_factors, predictions):
    """Generate comprehensive market analysis with factors affecting price"""
    analysis = {
        'coin': coin_name,
        'symbol': symbol,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'factors': {}
    }

    # 1. Sentiment analysis
    if sentiment_data:
        sentiment_score = sentiment_data.get('sentiment_score', 0)
        analysis['factors']['sentiment'] = {
            'score': sentiment_score,
            'magnitude': sentiment_data.get('sentiment_magnitude', 0),
            'article_count': sentiment_data.get('article_count', 0),
            'impact': 'positive' if sentiment_score > 0.1 else 'negative' if sentiment_score < -0.1 else 'neutral',
            'estimated_price_impact': f"{sentiment_score * 3:.2f}%"
        }

    # 2. Market correlation factors
    if market_factors:
        analysis['factors']['market_correlation'] = {}

        # S&P 500 correlation
        if 'sp500' in market_factors:
            sp500_avg_change = np.mean(market_factors['sp500'][-30:]) * 100 if len(market_factors['sp500']) >= 30 else 0
            analysis['factors']['market_correlation']['sp500'] = {
                'recent_trend': 'up' if sp500_avg_change > 0 else 'down',
                'avg_daily_change': f"{sp500_avg_change:.2f}%",
                'impact': 'Traditional markets show correlation with crypto, ' +
                         ('potentially positive for crypto prices' if sp500_avg_change > 0 else 'potentially negative for crypto prices')
            }

        # Bitcoin dominance
        if 'btc_dominance' in market_factors:
            btc_dom = market_factors['btc_dominance']
            if symbol.upper() == 'BTC' or symbol.upper() == 'BTC-USD':
                impact = f"High BTC dominance ({btc_dom}%) is positive for Bitcoin specifically"
            else:
                impact = "High BTC dominance typically means altcoins underperform Bitcoin" if btc_dom > 50 else "Lower BTC dominance typically allows altcoins to gain market share"

            analysis['factors']['market_correlation']['btc_dominance'] = {
                'current_value': f"{btc_dom}%",
                'impact': impact
            }

        # Dollar strength
        if 'dxy' in market_factors:
            dxy_trend = np.mean(market_factors['dxy'][-14:]) * 100 if len(market_factors['dxy']) >= 14 else 0
            analysis['factors']['market_correlation']['dollar_strength'] = {
                'recent_trend': 'strengthening' if dxy_trend > 0 else 'weakening',
                'impact': 'Dollar strength typically has negative correlation with crypto prices' if dxy_trend > 0 else 'Dollar weakness typically has positive correlation with crypto prices'
            }

        # Market fear
        if 'vix' in market_factors and len(market_factors['vix']) > 0:
            recent_vix = market_factors['vix'][-1] if len(market_factors['vix']) > 0 else 20

            # Extract the scalar value from the array (if it is an array)
            recent_vix = recent_vix.item() if isinstance(recent_vix, np.ndarray) else recent_vix

            fear_level = 'extreme fear' if recent_vix > 30 else 'fear' if recent_vix > 20 else 'neutral' if recent_vix > 15 else 'optimism'

            analysis['factors']['market_correlation']['market_volatility'] = {
                'vix_level': f"{recent_vix:.2f}",  # Now formatting a scalar value
                'fear_level': fear_level,
                'impact': f"Market is in {fear_level} state - " +
                         ('typically negative for risk assets' if recent_vix > 20 else 'favorable for risk assets')
            }

        # Fear & Greed Index
        if 'fear_greed' in market_factors:
            fg_value = market_factors['fear_greed']
            fg_sentiment = 'extreme fear' if fg_value <= 25 else 'fear' if fg_value <= 40 else 'neutral' if fg_value <= 60 else 'greed' if fg_value <= 80 else 'extreme greed'

            analysis['factors']['market_correlation']['fear_greed_index'] = {
                'value': fg_value,
                'sentiment': fg_sentiment,
                'impact': 'Contrarian indicator - extreme values often precede market reversals. ' +
                         ('Current extreme fear could signal buying opportunity' if fg_value <= 25 else
                          'Current extreme greed could signal market top' if fg_value >= 80 else
                          f"Current {fg_sentiment} state suggests normal market conditions")
            }

    # 3. Technical analysis factors
    analysis['factors']['technical'] = {
        'short_term_trend': predictions.get('price_direction', ''),
        'prediction_confidence': f"{predictions.get('confidence', 0):.1f}/10",
        'volatility_expectation': predictions.get('volatility', 'moderate'),
        'key_support': predictions.get('support', 'N/A'),
        'key_resistance': predictions.get('resistance', 'N/A')
    }

    # 4. External factors
    analysis['factors']['external'] = {
        'regulatory_environment': 'Monitoring global regulatory developments',
        'institutional_interest': 'Tracking institutional fund flows and announcements',
        'technology_developments': f"Following {coin_name} ecosystem updates and improvements",
        'market_liquidity': 'Analyzing exchange volumes and market depth'
    }

    # 5. Overall price projection
    analysis['price_projection'] = {
        'direction': predictions.get('price_direction', ''),
        'short_term': predictions.get('next_day', ''),
        'medium_term': predictions.get('five_day', ''),
        'confidence': predictions.get('confidence', 5),
        'factors_summary': predictions.get('summary', '')
    }

    return analysis

# Interactive UI components with enhanced features
def create_advanced_ui():
    """Create an advanced UI for cryptocurrency analysis"""
    # Map of top cryptocurrencies to CoinGecko IDs
    crypto_map = {
        'BTC-USD': 'bitcoin',
        'ETH-USD': 'ethereum',
        'BNB-USD': 'binancecoin',
        'XRP-USD': 'ripple',
        'ADA-USD': 'cardano',
        'DOGE-USD': 'dogecoin',
        'SOL-USD': 'solana',
        'DOT-USD': 'polkadot',
        'LTC-USD': 'litecoin',
        'MATIC-USD': 'matic-network',
        'AVAX-USD': 'avalanche-2',
        'ATOM-USD': 'cosmos',
        'LINK-USD': 'chainlink',
        'UNI-USD': 'uniswap',
        'ALGO-USD': 'algorand',
        'NEAR-USD': 'near',
        'FTM-USD': 'fantom',
        'AAVE-USD': 'aave',
        'GRT-USD': 'the-graph',
        'SAND-USD': 'the-sandbox'
    }

    # List of top cryptocurrencies
    crypto_options = list(crypto_map.keys())

    # UI Components
    search_box = widgets.Text(description='Search:', placeholder='Enter crypto name or symbol')
    crypto_dropdown = widgets.Dropdown(options=crypto_options, description='Crypto:', value='BTC-USD')
    search_button = widgets.Button(description="Search")
    fetch_button = widgets.Button(description="Analyze & Predict")
    days_selector = widgets.IntSlider(value=30, min=7, max=365, step=1, description='Chart Days:')
    prediction_days = widgets.IntSlider(value=5, min=1, max=30, step=1, description='Forecast Days:')
    model_type = widgets.RadioButtons(
        options=['Standard', 'Enhanced (Slower)', 'Simple (Faster)'],
        description='Model Type:',
        value='Standard'
    )
    include_market = widgets.Checkbox(value=True, description='Include Market Factors')
    include_sentiment = widgets.Checkbox(value=True, description='Include Sentiment Analysis')
    output_display = widgets.Output()

    # Search function handler
    def on_search_click(b):
        with output_display:
            clear_output(wait=True)
            query = search_box.value.strip()
            if not query:
                print("Please enter a cryptocurrency name or symbol to search")
                return

            results = search_cryptocurrency(query)
            if not results:
                print(f"No results found for '{query}'. Try a different search term.")
                return

            print(f"Search results for '{query}':")
            for i, coin in enumerate(results):
                print(f"{i+1}. {coin['name']} ({coin['symbol']}) - Rank: {coin['market_cap_rank']}")

            # Add the top result to the dropdown if not already there
            top_result = f"{results[0]['symbol']}-USD"
            if top_result not in crypto_dropdown.options:
                new_options = list(crypto_dropdown.options) + [top_result]
                crypto_dropdown.options = new_options

            # Set the dropdown to the top result
            if top_result in crypto_dropdown.options:
                crypto_dropdown.value = top_result
                print(f"\nSelected {results[0]['name']} ({top_result}) for analysis")

            # Also store the CoinGecko ID in the crypto_map
            crypto_map[top_result] = results[0]['id']

    # Connect search button to handler
    search_button.on_click(on_search_click)

    # Main analysis function
    def fetch_and_predict(_=None):
        with output_display:
            clear_output(wait=True)

            selected_crypto = crypto_dropdown.value  # Get selected cryptocurrency
            include_market_factors = include_market.value
            include_sentiment_analysis = include_sentiment.value
            days_to_show = days_selector.value
            days_to_predict = prediction_days.value
            selected_model = model_type.value

            print(f"Starting analysis for {selected_crypto}...")
            print(f"Analysis settings: Show {days_to_show} days, Predict {days_to_predict} days, Model: {selected_model}")

            # Map to CoinGecko ID
            coin_id = crypto_map.get(selected_crypto)
            if not coin_id:
                print(f"Could not find CoinGecko ID for {selected_crypto}, searching...")
                base_symbol = selected_crypto.split('-')[0] if '-' in selected_crypto else selected_crypto
                results = search_cryptocurrency(base_symbol)
                if results and len(results) > 0:
                    coin_id = results[0]['id']
                    crypto_map[selected_crypto] = coin_id
                    print(f"Found coin ID: {coin_id} for {selected_crypto}")
                else:
                    print(f"Could not find CoinGecko ID for {selected_crypto}")

            # Fetch USD to INR rate
            usd_to_inr = get_usd_to_inr()
            print(f"Current USD to INR rate: {usd_to_inr}")

            # Get market factors if enabled
            market_factors = {}
            if include_market_factors:
                print("Fetching market factors...")
                market_factors = fetch_market_factors()

            # Fetch cryptocurrency data
            print(f"Fetching data for {selected_crypto}...")
            data, coin_id = fetch_crypto_data_multi_source(selected_crypto, coin_id)

            if data is None or data.empty:
                print("Failed to fetch cryptocurrency data from all sources. Please try again later.")
                print("This could be due to API rate limits or temporary service issues.")
                return

            # Get coin name for display purposes
            if coin_id in crypto_map.values():
                coin_name = [k.split('-')[0] for k, v in crypto_map.items() if v == coin_id][0]
            else:
                coin_name = selected_crypto.split('-')[0]

            # Get sentiment data if enabled
            sentiment_data = {}
            if include_sentiment_analysis:
                print(f"Analyzing sentiment for {coin_name}...")
                sentiment_data = get_crypto_sentiment(coin_name, selected_crypto.split('-')[0])

            # Create a copy of the price data
            data_price = data[['Open', 'High', 'Low', 'Close']].copy()
            if 'Volume' in data.columns:
                data_price['Volume'] = data['Volume']
            else:
                data_price['Volume'] = np.random.uniform(1000000, 10000000, size=len(data_price))

            # Check if we have enough data for meaningful analysis
            if len(data_price) < 30:
                print(f"Not enough data points ({len(data_price)}). Need at least 30 for predictions.")
                return

            # Convert to INR
            for col in ['Open', 'High', 'Low', 'Close']:
                data_price[f'{col}_INR'] = data_price[col] * usd_to_inr

            print(f"Successfully loaded {len(data_price)} data points")

            # Calculate technical indicators
            print("Calculating technical indicators...")
            data_with_indicators = add_technical_indicators(data_price)

            # Display recent price information
            print("\nRecent price information:")
            print(f"Current price: ₹{data_price['Close_INR'].iloc[-1]:.2f} (${data_price['Close'].iloc[-1]:.2f})")

            if len(data_price) >= 8:
                week_change = ((data_price['Close'].iloc[-1] / data_price['Close'].iloc[-8]) - 1) * 100
                print(f"7-day change: {week_change:.2f}%")

            if len(data_price) >= 31:
                month_change = ((data_price['Close'].iloc[-1] / data_price['Close'].iloc[-31]) - 1) * 100
                print(f"30-day change: {month_change:.2f}%")

            # Prepare data for model based on selected complexity
            if selected_model == 'Simple (Faster)':
                # Use fewer features for faster processing
                features = ['Close_INR', 'SMA_7', 'SMA_14', 'EMA_14', 'RSI']
                time_step = 7
            elif selected_model == 'Enhanced (Slower)':
                # Use all available indicators for best accuracy
                features = [
                    'Close_INR', 'Volume', 'SMA_7', 'SMA_14', 'SMA_30', 'EMA_14',
                    'RSI', 'MACD_line', 'MACD_signal', 'STOCH_k', 'STOCH_d',
                    'BB_width', 'ATR', 'ROC_5', 'ROC_14', 'Volatility', 'ADX'
                ]
                time_step = 21
            else:  # Standard
                # Balanced approach
                features = [
                    'Close_INR', 'SMA_7', 'SMA_14', 'SMA_30', 'EMA_14',
                    'RSI', 'MACD_diff', 'ROC_5', 'Volatility'
                ]
                time_step = 14

            # Ensure all features exist in the dataframe
            features = [f for f in features if f in data_with_indicators.columns]

            # Add market sentiment as a feature if available
            if sentiment_data and 'sentiment_score' in sentiment_data:
                # Create a sentiment column with the same value for all rows
                data_with_indicators['Sentiment'] = sentiment_data['sentiment_score']
                features.append('Sentiment')

            # Train ensemble models
            lstm_model, rf_model, scaler = train_ensemble_model(
                data_with_indicators, features, 'Close_INR', time_step
            )

            if lstm_model is None or rf_model is None or scaler is None:
                print("Failed to train prediction models. Please try again with different parameters.")
                return

            # Get the last time_step days of data for prediction
            recent_data = data_with_indicators[features].values[-time_step:]
            recent_data_scaled = scaler.transform(recent_data)

            # Reshape for LSTM prediction
            X_recent = recent_data_scaled.reshape(1, time_step, len(features))

            # Predictions
            future_predictions = []
            current_sequence = recent_data_scaled.copy()

            # Predict future days
            print(f"\nPredicting future prices for next {days_to_predict} days...")
            for i in range(days_to_predict):
                # Reshape for prediction
                X_future = current_sequence.reshape(1, time_step, len(features))

                # Make ensemble prediction
                next_pred = make_ensemble_prediction(
                    lstm_model, rf_model, scaler, X_future, features, time_step
                )

                # Create a new data point with predicted Close_INR and estimated features
                new_point = np.zeros(len(features))
                new_point[features.index('Close_INR')] = next_pred[0]

                # Update other features based on simple estimates
                # This is a simplified approach - in a real system you'd have more sophisticated updates
                for j, feature in enumerate(features):
                    if feature == 'Close_INR':
                        continue  # Already set
                    elif feature.startswith('SMA_'):
                        window = int(feature.split('_')[1])
                        if window <= time_step:
                            # Update moving average
                            prev_values = current_sequence[-window+1:, features.index('Close_INR')]
                            new_point[j] = (np.sum(prev_values) + next_pred[0]) / window
                        else:
                            # Keep the previous value for longer windows
                            new_point[j] = current_sequence[-1, j]
                    elif feature == 'Volatility':
                        # Keep volatility similar to recent values
                        new_point[j] = current_sequence[-1, j]
                    elif feature == 'RSI':
                        # Simple RSI approximation
                        current_rsi = current_sequence[-1, features.index('RSI')]
                        price_change = next_pred[0] - current_sequence[-1, features.index('Close_INR')]
                        # Move RSI in the direction of price change, but limit movement
                        if price_change > 0:
                            new_point[j] = min(current_rsi + 5, 95)  # Up with ceiling
                        else:
                            new_point[j] = max(current_rsi - 5, 5)   # Down with floor
                    elif feature == 'Sentiment':
                        # Keep sentiment constant for predictions
                        new_point[j] = current_sequence[-1, j]
                    else:
                        # For other indicators, use the last value as an approximation
                        new_point[j] = current_sequence[-1, j]

                # Store prediction
                future_predictions.append(new_point)

                # Update sequence for next prediction
                current_sequence = np.vstack([current_sequence[1:], new_point])

            # Convert future predictions to original scale
            future_pred_array = np.array(future_predictions)
            future_data = np.zeros((len(future_pred_array), len(features)))
            future_data[:, features.index('Close_INR')] = future_pred_array[:, features.index('Close_INR')]
            future_pred_inr = scaler.inverse_transform(future_data)[:, features.index('Close_INR')]

            # Create dates for future predictions
            last_date = data_with_indicators.index[-1]
            future_dates = [last_date + timedelta(days=i+1) for i in range(days_to_predict)]

            # Calculate model accuracy on historical data (last 30 days)
            # Prepare recent test data
            test_window = min(30, len(data_with_indicators) - time_step)
            recent_test_X = []
            recent_test_y = []

            for i in range(len(data_with_indicators) - test_window, len(data_with_indicators) - time_step):
                recent_test_X.append(data_with_indicators[features].values[i:i+time_step])
                recent_test_y.append(data_with_indicators['Close_INR'].values[i+time_step])

            recent_test_X = np.array(recent_test_X)
            recent_test_y = np.array(recent_test_y)

            # Scale the test data
            recent_test_X_scaled = np.array([scaler.transform(x) for x in recent_test_X])

            # Make predictions
            lstm_preds = lstm_model.predict(recent_test_X_scaled)
            rf_preds = rf_model.predict(recent_test_X_scaled.reshape(recent_test_X_scaled.shape[0], -1))

            # Create ensemble predictions
            ensemble_preds = lstm_preds * 0.7 + rf_preds.reshape(-1, 1) * 0.3

            # Convert predictions back to original scale
            pred_data = np.zeros((len(ensemble_preds), len(features)))
            pred_data[:, features.index('Close_INR')] = ensemble_preds.flatten()

            recent_preds = scaler.inverse_transform(pred_data)[:, features.index('Close_INR')]

            # Calculate error metrics
            mae = mean_absolute_error(recent_test_y, recent_preds)
            mse = mean_squared_error(recent_test_y, recent_preds)
            rmse = np.sqrt(mse)
            mape = np.mean(np.abs((recent_test_y - recent_preds) / recent_test_y)) * 100

            print("\nModel Performance Metrics:")
            print(f"Mean Absolute Error: ₹{mae:.2f}")
            print(f"Root Mean Squared Error: ₹{rmse:.2f}")
            print(f"Mean Absolute Percentage Error: {mape:.2f}%")

            # Calculate model confidence score (0-10)
            if mape <= 1:
                confidence = 10
            elif mape <= 3:
                confidence = 9
            elif mape <= 5:
                confidence = 8
            elif mape <= 7:
                confidence = 7
            elif mape <= 10:
                confidence = 6
            elif mape <= 15:
                confidence = 5
            elif mape <= 20:
                confidence = 4
            elif mape <= 25:
                confidence = 3
            elif mape <= 30:
                confidence = 2
            else:
                confidence = 1

            print(f"Model Confidence Score: {confidence}/10")

            # Display future predictions
            print("\nFuture Price Predictions:")
            for date, price in zip(future_dates, future_pred_inr):
                print(f"{date.strftime('%Y-%m-%d')}: ₹{price:.2f} (${price/usd_to_inr:.2f})")

            # Plot historical and future prices
            plt.figure(figsize=(12,6))

            # Plot historical data (last N days)
            hist_days = min(days_to_show, len(data_with_indicators))
            plt.plot(data_with_indicators.index[-hist_days:],
                     data_with_indicators['Close_INR'].values[-hist_days:],
                     label='Historical Price', color='blue')

            # Plot future predictions
            plt.plot(future_dates, future_pred_inr,
                     label='Price Predictions', color='red',
                     marker='o', linestyle='--')

            # Add vertical line for current date
            plt.axvline(x=last_date, color='green', linestyle='-',
                       alpha=0.3, label='Current Date')

            # Add confidence bands based on model accuracy
            uncertainty = mape / 100
            plt.fill_between(future_dates,
                            future_pred_inr * (1 - uncertainty),
                            future_pred_inr * (1 + uncertainty),
                            color='red', alpha=0.2, label='Uncertainty Range')

            plt.legend()
            plt.title(f'{selected_crypto} Price Prediction ({days_to_predict} Days) in INR')
            plt.xticks(rotation=45)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.show()

            # Plot additional technical indicators
            plt.figure(figsize=(12,8))

            # Create subplot for RSI
            plt.subplot(3, 1, 1)
            plt.plot(data_with_indicators.index[-hist_days:],
                     data_with_indicators['RSI'].values[-hist_days:],
                     label='RSI', color='purple')
            plt.axhline(y=70, color='r', linestyle='--', alpha=0.5)
            plt.axhline(y=30, color='g', linestyle='--', alpha=0.5)
            plt.title('Relative Strength Index (RSI)')
            plt.legend()
            plt.grid(True, alpha=0.3)

            # Create subplot for MACD
            plt.subplot(3, 1, 2)
            if 'MACD_line' in data_with_indicators.columns and 'MACD_signal' in data_with_indicators.columns:
                plt.plot(data_with_indicators.index[-hist_days:],
                         data_with_indicators['MACD_line'].values[-hist_days:],
                         label='MACD Line', color='blue')
                plt.plot(data_with_indicators.index[-hist_days:],
                         data_with_indicators['MACD_signal'].values[-hist_days:],
                         label='Signal Line', color='red')
                plt.title('Moving Average Convergence Divergence (MACD)')
                plt.legend()
                plt.grid(True, alpha=0.3)

            # Create subplot for Bollinger Bands
            plt.subplot(3, 1, 3)
            if 'BB_high' in data_with_indicators.columns and 'BB_low' in data_with_indicators.columns:
                plt.plot(data_with_indicators.index[-hist_days:],
                         data_with_indicators['Close_INR'].values[-hist_days:],
                         label='Price', color='blue')
                plt.plot(data_with_indicators.index[-hist_days:],
                         data_with_indicators['BB_high'].values[-hist_days:],
                         label='Upper Band', color='red', linestyle='--')
                plt.plot(data_with_indicators.index[-hist_days:],
                         data_with_indicators['BB_mid'].values[-hist_days:],
                         label='Middle Band', color='orange', linestyle='-.')
                plt.plot(data_with_indicators.index[-hist_days:],
                         data_with_indicators['BB_low'].values[-hist_days:],
                         label='Lower Band', color='green', linestyle='--')
                plt.title('Bollinger Bands')
                plt.legend()
                plt.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.show()

            # Calculate support and resistance levels
            recent_prices = data_with_indicators['Close_INR'].values[-30:]
            support_level = np.percentile(recent_prices, 25)
            resistance_level = np.percentile(recent_prices, 75)

            # Prepare predictions dictionary for market analysis
            price_direction = "bullish 📈" if future_pred_inr[0] > data_with_indicators['Close_INR'].iloc[-1] else "bearish 📉"
            daily_change = ((future_pred_inr[0] / data_with_indicators['Close_INR'].iloc[-1]) - 1) * 100
            weekly_change = ((future_pred_inr[-1] / data_with_indicators['Close_INR'].iloc[-1]) - 1) * 100

            predictions_data = {
                'next_day': f"₹{future_pred_inr[0]:.2f} (${future_pred_inr[0]/usd_to_inr:.2f})",
                'five_day': f"₹{future_pred_inr[-1]:.2f} (${future_pred_inr[-1]/usd_to_inr:.2f})",
                'price_direction': price_direction,
                'daily_change': f"{daily_change:.2f}%",
                'five_day_change': f"{weekly_change:.2f}%",
                'confidence': confidence,
                'support': f"₹{support_level:.2f}",
                'resistance': f"₹{resistance_level:.2f}",
                'volatility': 'high' if data_with_indicators['Volatility'].iloc[-1] > 5 else 'moderate' if data_with_indicators['Volatility'].iloc[-1] > 2 else 'low',
                'summary': f"The model predicts a {price_direction} trend with {confidence}/10 confidence based on technical indicators and market factors."
            }

            # Generate market analysis if enabled
            if include_market_factors or include_sentiment_analysis:
                print("\n--- Market Factors Analysis ---")
                market_analysis = generate_market_analysis(
                    coin_name, selected_crypto, sentiment_data, market_factors, predictions_data
                )

                # Display market factors
                if 'factors' in market_analysis:
                    # Display sentiment analysis if available
                    if include_sentiment_analysis and 'sentiment' in market_analysis['factors']:
                        sentiment = market_analysis['factors']['sentiment']
                        print(f"\nSentiment Analysis:")
                        print(f"Score: {sentiment['score']:.2f} ({sentiment['impact']} sentiment)")
                        print(f"Estimated Price Impact: {sentiment['estimated_price_impact']}")

                    # Display market correlation factors
                    if include_market_factors and 'market_correlation' in market_analysis['factors']:
                        print("\nMarket Correlation Factors:")
                        for factor, details in market_analysis['factors']['market_correlation'].items():
                            print(f"- {factor.replace('_', ' ').title()}: {details.get('impact', '')}")

            # Trading recommendation
            print("\nTrading Recommendation:")

            # Simple recommendation system based on predicted trends and market factors
            if weekly_change > 5 and confidence >= 7:
                recommendation = "Strong Buy 🟢🟢"
            elif weekly_change > 2 or (weekly_change > 0 and confidence >= 6):
                recommendation = "Buy 🟢"
            elif weekly_change > -2 or confidence < 4:
                recommendation = "Hold ⚪"
            elif weekly_change > -5:
                recommendation = "Sell 🔴"
            else:
                recommendation = "Strong Sell 🔴🔴"

            print(f"{recommendation} - {predictions_data['summary']}")
            print("\nNote: This is for educational purposes only. Always do your own research before investing.")

    # Connect button click to function
    fetch_button.on_click(fetch_and_predict)

    # Create UI layout
    search_ui = widgets.HBox([search_box, search_button])
    model_ui = widgets.VBox([crypto_dropdown, days_selector, prediction_days, model_type])
    options_ui = widgets.VBox([include_market, include_sentiment])
    control_ui = widgets.HBox([model_ui, options_ui])

    # Return all UI components
    return widgets.VBox([
        widgets.HTML("<h2>Advanced Cryptocurrency Price Prediction Tool</h2>"),
        widgets.HTML("<p>Search for any cryptocurrency or select from popular options</p>"),
        search_ui,
        control_ui,
        fetch_button,
        output_display
    ])

# Main function to run the application
def main():
    """Main function to run the cryptocurrency analysis tool"""
    print("Starting Cryptocurrency Analysis and Prediction Tool...")
    print(f"Model Version: {MODEL_VERSION}")
    print("Created by: Crypto Analysis Team")
    print("----------------------------------------")

    # Create and display the UI
    ui = create_advanced_ui()
    display(ui)

    print("Ready to analyze cryptocurrency data")
    print("Select a cryptocurrency and click 'Analyze & Predict' to begin")

# When run directly
if __name__ == "__main__":
    main()
