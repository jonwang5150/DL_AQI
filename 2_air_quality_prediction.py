# -*- coding: utf-8 -*-
"""
Created on Tue Aug 11 16:42:09 2026

@author: jon
"""

#%% 1.資料引入
import pandas as pd
import numpy as np
# 此資料集為20250812-20260811木柵觀測站空氣品質資料，每一小時會監測一次空氣中各個氣體或汙染物濃度，並計算出AQI
#df = pd.read_csv("20260515_20260615.csv",encoding='utf8')
# df = pd.read_csv("AQI_dataset/20250812-20260811.csv",encoding='utf-8-sig')
df = pd.read_csv("aqi_hour_concat.csv",encoding='utf-8-sig')


print(df.head())
#     測站                日期  AQI 空氣品質指標   O3 PM2.5 PM10    CO   SO2  NO2
# 0  木柵站  2025/08/12 00:00   41   懸浮微粒  5.9     8   26  0.29  1.92  6.2
# 1  木柵站  2025/08/12 01:00   41   懸浮微粒  5.8     7   24  0.29  1.86  4.9
# 2  木柵站  2025/08/12 02:00   40   懸浮微粒  8.3     7   23  0.26  1.71  4.1
# 3  木柵站  2025/08/12 03:00   42   懸浮微粒  6.5     5   31  0.23  1.78  3.2
# 4  木柵站  2025/08/12 04:00   44   懸浮微粒  5.2     6   33  0.26  1.96  3.8
print('--------------------------------------------')
print(df.isnull().sum())    #都顯示0
print('--------------------------------------------')
columns=list(df.columns)
print(columns)
#['測站', '日期', 'AQI', '空氣品質指標', 'O3', 'PM2.5', 'PM10', 'CO', 'SO2', 'NO2']
print('--------------------------------------------')
df.info()
# <class 'pandas.DataFrame'>
# RangeIndex: 8723 entries, 0 to 8722
# Data columns (total 10 columns):
#  #   Column  Non-Null Count  Dtype
# ---  ------  --------------  -----
#  0   測站      8723 non-null   str  
#  1   日期      8723 non-null   str  
#  2   AQI     8723 non-null   int64
#  3   空氣品質指標  8723 non-null   str  
#  4   O3      8723 non-null   str  
#  5   PM2.5   8723 non-null   str  
#  6   PM10    8723 non-null   str  
#  7   CO      8723 non-null   str  
#  8   SO2     8723 non-null   str  
#  9   NO2     8723 non-null   str  
# dtypes: int64(1), str(9)
# memory usage: 1.1 MB
#%%  2.資料處理-1
df['日期'] = pd.to_datetime(df['日期'])
df = df.sort_values('日期').reset_index(drop=True)
print(df["日期"].is_monotonic_increasing)  #確認時間為由遠至近排序

print('空氣品質指標欄位有以下資料: ',set(df['空氣品質指標']))
# {'細懸浮微粒', '二氧化氮小時值', '臭氧8小時', '懸浮微粒'}
# 此欄位可能為主要汙染物來源,可能由其他欄位選一位最為嚴重的來做為代表,為避免資料洩漏（Data Leakage）,刪除此欄位
df=df.drop(columns=['空氣品質指標','測站'])
cols= ['O3', 'PM2.5', 'PM10', 'CO', 'SO2', 'NO2']

#%% 2.資料處理-2
# 資料集有兩種缺失,一種是欄位有空，另一種是timestamp有缺失,會造成時間的空窗

#df[cols] = df[cols].astype(float)
# 若操作上個程式碼會出現ValueError: could not convert string to float: '-',
# 原來是有空欄位('-'),沒被df.isnull()抓出來
print(df[(df == "-").any(axis=1)])
df_lost=df[(df == "-").any(axis=1)]
#                       日期  AQI    O3 PM2.5 PM10    CO   SO2   NO2
# 15   2025-08-12 15:00:00   41  52.3     -    -  0.29  3.57   9.5
# 33   2025-08-13 09:00:00   24  18.9     -    -  0.22  2.27   3.7
# 34   2025-08-13 10:00:00   25     -     -    -     -     -     -
# 35   2025-08-13 11:00:00   12     -     -    -     -     -     -
# 36   2025-08-13 12:00:00   13  19.5     6    -  0.37  1.27   2.2
#                  ...  ...   ...   ...  ...   ...   ...   ...
# 8624 2026-08-07 21:00:00   66  19.4    20    -  0.35  0.57  17.4
# 8625 2026-08-07 22:00:00   71    23    28    -  0.35  0.84  16.4
# 8670 2026-08-09 19:00:00   25  12.8    15    -  0.42  0.64   8.8
# 8671 2026-08-09 20:00:00   29   9.8    13    -  0.42  0.79   8.4
# 8672 2026-08-09 21:00:00   28   8.5     7    -  0.43  0.65   6.9
# [293 rows x 8 columns]
# 共293列有空資料

# 將各欄位資料格式轉為數值，空值則轉為nan
for c in cols:
    df[c] = pd.to_numeric(df[c], errors='coerce')
#df.info()

# 線性補值
df[cols] = df[cols].interpolate(method='linear')
#df.info()

# 建立理論上應該存在的每小時時間軸
expected = pd.date_range(
    start=df['日期'].min(),
    end=df['日期'].max(),
    freq='h'
)

# 找出消失的時間
missing_times = expected.difference(df['日期'])
print("理論應有:", len(expected))   #8760
print("實際資料:", len(df))         #8723
print("缺少時間點:", len(missing_times))     #37
print(missing_times)
# DatetimeIndex(['2025-11-12 17:00:00', '2025-11-12 18:00:00',
#                '2025-11-12 19:00:00', '2025-11-12 20:00:00',
#                '2025-11-12 21:00:00', '2025-11-12 22:00:00',
#                '2025-11-12 23:00:00', '2025-11-13 09:00:00',
#                '2025-12-15 06:00:00', '2025-12-15 07:00:00',
#                '2025-12-25 01:00:00', '2025-12-25 02:00:00',
#                '2025-12-25 03:00:00', '2025-12-25 04:00:00',
#                '2025-12-25 05:00:00', '2025-12-25 06:00:00',
#                '2025-12-25 07:00:00', '2025-12-26 08:00:00',
#                '2026-02-11 22:00:00', '2026-03-17 05:00:00',
#                '2026-05-13 01:00:00', '2026-05-13 02:00:00',
#                '2026-05-13 03:00:00', '2026-05-13 04:00:00',
#                '2026-05-13 05:00:00', '2026-05-13 06:00:00',
#                '2026-05-13 07:00:00', '2026-06-22 06:00:00',
#                '2026-06-22 15:00:00', '2026-07-15 17:00:00',
#                '2026-07-15 18:00:00', '2026-07-15 19:00:00',
#                '2026-07-15 20:00:00', '2026-07-15 21:00:00',
#                '2026-07-15 22:00:00', '2026-07-15 23:00:00',
#                '2026-07-23 14:00:00'],
#               dtype='datetime64[us]', freq=None)

# 此資料集共有37個時間消失
# 分析這37筆空窗期，看其連續的時間長度，並統計次數
time_diff = df['日期'].diff()
print(time_diff.value_counts())
# # 日期
# 0 days 01:00:00    8710    (沒有缺失的筆數)
# 0 days 02:00:00       7    (代表缺1小時的筆數)
# 0 days 08:00:00       4    (代表缺7小時的筆數)
# 0 days 03:00:00       1    (代表缺2小時的筆數)
# Name: count, dtype: int64
# 後續再資料切分時,會設計不把這些有缺時間的time sequence算進去,以免造成序列資料失真





#%%  3.圖表分析
import plotly.express as px
import plotly.io as pio
pio.renderers.default = "browser"


fig1 = px.line(df, x='日期', y='AQI', title='AQI Trend Over Time')
fig1.show()

fig2 = px.scatter_matrix(
    df,
    dimensions=['AQI', 'PM2.5', 'PM10', 'CO', 'NO2'],
    title='Air Quality Relationships'
)
fig2.show()


#%%  4.資料切分 -> normalize ->from sklearn.model_selection import train_test_split time_sequence
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
# 先做train_test分割,切分資料X Y

train_df, test_df = train_test_split(
    df,
    test_size=0.2,
    shuffle=False
)

print("訓練期間:", train_df['日期'].min(), "~", train_df['日期'].max())
print("測試期間:", test_df['日期'].min(), "~", test_df['日期'].max())
print("訓練期間:", train_df['日期'].min(), "~", train_df['日期'].max())
print("測試期間:", test_df['日期'].min(), "~", test_df['日期'].max())

features=['O3', 'PM2.5', 'PM10', 'CO', 'SO2', 'NO2']

# normalize
scaler = StandardScaler()
train_df[features] = scaler.fit_transform(train_df[features])
test_df[features] = scaler.transform(test_df[features])


# 使用過去24小時各空氣數據指標,預測下一小時AQI
train_X, train_y = [], []
window_size=24
for i in range(window_size, len(train_df)):
    window = train_df.iloc[i-window_size:i]
    # 確認 24 小時連續
    time_diff = window['日期'].diff().dropna()
    if not (time_diff == pd.Timedelta(hours=1)).all():
        continue
    
    # 確認 target 是 window 後的下一小時，如果不是的話這個sequence就不要留
    if train_df.iloc[i]['日期'] - window['日期'].iloc[-1] != pd.Timedelta(hours=1):
        continue
    train_X.append(window[features].values)
    train_y.append(train_df.iloc[i]['AQI'])

# 需要把train_df最後24小時的資料併入作為test_x資料,不然會浪費前test_df前24筆(當作test_y)
history = train_df.tail(window_size)
test_data = pd.concat([history, test_df], ignore_index=True)
test_start = test_df['日期'].min()
test_X, test_y = [], []
for i in range(window_size, len(test_data)):
    window = test_data.iloc[i-window_size:i]
    # 確認 24 小時連續
    time_diff = window['日期'].diff().dropna()
    if not (time_diff == pd.Timedelta(hours=1)).all():
        continue
    
    # 確認 target 是 window 後的下一小時，如果不是的話這個 sequence 就不要留
    if test_data.iloc[i]['日期'] - window['日期'].iloc[-1] != pd.Timedelta(hours=1):
        continue
    # target 必須屬於 Test
    if test_data.iloc[i]['日期'] < test_start:
        continue
    test_X.append(window[features].values)
    test_y.append(test_data.iloc[i]['AQI'])



#%% 5.轉成tensor,包裝成dataloader
import torch
from torch.utils.data import TensorDataset, DataLoader

train_X = np.array(train_X)
train_y = np.array(train_y)
test_X = np.array(test_X)
test_y = np.array(test_y)
print(train_X.shape)    #(6780, 24, 6)
print(train_y.shape)    #(6780,)
print(test_X.shape)     #(1638, 24, 6)
print(test_y.shape)     #(1638,)


X_train = torch.tensor(train_X, dtype=torch.float32)
y_train = torch.tensor(train_y, dtype=torch.float32)
X_test = torch.tensor(test_X, dtype=torch.float32)
y_test = torch.tensor(test_y, dtype=torch.float32)

train_loader = DataLoader(
    TensorDataset(X_train, y_train),
    batch_size=32,
    shuffle=True
)

test_loader = DataLoader(
    TensorDataset(X_test, y_test),
    batch_size=32,
    shuffle=False
)
#%% 6.模型設計
# 此為num_layers的模型
# import torch.nn as nn

# class LSTMModel(nn.Module):
#     def __init__(self,
#                  input_size=6,
#                  hidden_size=128,
#                  num_layers=2,
#                  dropout=0.2
#                  ):
#         super().__init__()
        
#         self.lstm = nn.LSTM(
#             input_size=input_size,
#             hidden_size=hidden_size,
#             num_layers=num_layers,
#             batch_first=True,
#             dropout=dropout
#         )
        
#         self.fc = nn.Sequential(
#             nn.Linear(hidden_size, 64),
#             nn.ReLU(),
#             nn.Dropout(0.2),
#             nn.Linear(64, 32),
#             nn.ReLU(),
#             nn.Linear(32, 1)
#         )

#     def forward(self, x):
#         out, _ = self.lstm(x)
#         out = out[:, -1, :]   # 取最後時間步
#         out = self.fc(out)
#         return out.squeeze()
    
#%% 6.模型設計
import torch.nn as nn

class LSTMModel(nn.Module):
    def __init__(self,
                 input_size=6,
                 hidden_size=64,
                 num_layers=1,
                 ):
        super().__init__()
        
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        out = out[:, -1, :]   # 取最後時間步
        out = self.fc(out)
        return out.squeeze()


#%% 7.開始訓練
model = LSTMModel()

criterion = nn.MSELoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
epochs = 50

for epoch in range(epochs):
    model.train()
    
    total_loss = 0
    total_samples = 0
    for X_batch, y_batch in train_loader:
        
        pred = model(X_batch)
        loss = criterion(pred, y_batch)
        
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
      
        total_loss += loss.item()*X_batch.size(0)
        total_samples += X_batch.size(0)
    avg_loss = total_loss / total_samples
    print(f"Epoch {epoch+1}, Loss: {avg_loss:.4f}")

# 第一次測試 epoch=50:
# Epoch 43, Loss: 11.5555
# Epoch 44, Loss: 11.3119
# Epoch 45, Loss: 11.1660
# Epoch 46, Loss: 10.0479
# Epoch 47, Loss: 9.8490
# Epoch 48, Loss: 10.7653
# Epoch 49, Loss: 10.4780
# Epoch 50, Loss: 10.2488
#----------------------------------------------------
# 第二次測試 epoch=100:
# Epoch 93, Loss: 6.1064
# Epoch 94, Loss: 5.6022
# Epoch 95, Loss: 5.5848
# Epoch 96, Loss: 5.6560
# Epoch 97, Loss: 5.7274
# Epoch 98, Loss: 5.4086
# Epoch 99, Loss: 5.5134
# Epoch 100, Loss: 5.1887
#----------------------------------------------------
# 第三次測試 time_sequence=48 / epoch=100:
# Epoch 93, Loss: 4.1685
# Epoch 94, Loss: 4.2268
# Epoch 95, Loss: 4.1434
# Epoch 96, Loss: 4.1552
# Epoch 97, Loss: 3.9985
# Epoch 98, Loss: 3.9416
# Epoch 99, Loss: 4.1289
# Epoch 100, Loss: 3.7853
#----------------------------------------------------
# 第四次測試 time_sequence=24 / epoch=50 / 改回1 layer的模型:
# Epoch 43, Loss: 6.0854
# Epoch 44, Loss: 6.0696
# Epoch 45, Loss: 5.9255
# Epoch 46, Loss: 5.8628
# Epoch 47, Loss: 5.7417
# Epoch 48, Loss: 5.7159
# Epoch 49, Loss: 5.6536
# Epoch 50, Loss: 5.6137
#%% 8.跑測試集
model.eval()
all_preds = []
all_labels = []
with torch.no_grad():
    for X_batch, y_batch in test_loader:
        
        pred = model(X_batch)
        
        all_preds.append(pred)
        all_labels.append(y_batch)

all_preds = torch.cat(all_preds)
all_labels = torch.cat(all_labels)
mae = torch.mean(torch.abs(all_preds - all_labels))
rmse = torch.sqrt(torch.mean((all_preds - all_labels) ** 2))

print(mae.item(), rmse.item())

# time_sequence=24 / epoch=50
# 5.309279441833496 6.676910877227783
#----------------------------------------------------
# time_sequence=24 / epoch=100
# 4.656620979309082 6.162725448608398
#----------------------------------------------------
# time_sequence=48 / epoch=100
# 5.541021823883057 6.871032238006592
#----------------------------------------------------
# time_sequence=24 / epoch=50 / 改回1 layer的模型:
# 2.1646103858947754 3.0816593170166016
# mae跟rmse都降了
#%% 10.預測未來
# 將8/10 00:00 ~ 8/10 23:00資料取出
last_window = test_df.tail(24)[features].values

x = torch.tensor(last_window, dtype=torch.float32)
x = x.unsqueeze(0)  # (1, 6, 6)

model.eval()
with torch.no_grad():
    pred = model(x)

df_811=df[df['日期']>='2026-08-11']
print("8/11 AQI 預測:", pred.item(),"8/11 AQI 實際值:",df_811.iloc[0,1])
# 8/11 AQI 預測: 39.32701110839844 8/11 AQI 實際值: 48  (time_sequence=24 / epoch=50)
#----------------------------------------------------
# 8/11 AQI 預測: 39.807003021240234 8/11 AQI 實際值: 48  (time_sequence=24 / epoch=100)
# epoch增加一倍並未提升預測精準度
#----------------------------------------------------
# 8/11 AQI 預測: 38.818878173828125 8/11 AQI 實際值: 48  (time_sequence=48 / epoch=100)
# time_sequence改為48小時結果也差不多
#----------------------------------------------------
# 8/11 AQI 預測: 48.12952423095703 8/11 AQI 實際值: 48 (time_sequence=24 / epoch=50 / 改回1 layer的模型)
# 此次將time_sequence及epoch調成原本的模式，但是選用最簡單的模型，mae跟rsme都有下降，預測未來部分表現也很精準
# 增加 LSTM 層數並沒有帶來更好的預測效果；反而較簡單的 1-layer LSTM 在這次測試中表現非常好，也許資料量要提升更多才需要設計更深層的模型

#%% 11.儲存模型
model_path = "aqi_lstm_model.pth"
torch.save(
    {
        "model_state_dict": model.state_dict(),
        "model_config": {
            "input_size": len(features),
            "hidden_size": 64,
            "num_layers": 1,
        },
        "features": features,
        "window_size": window_size,
        "scaler_mean": scaler.mean_,
        "scaler_scale": scaler.scale_,
    },
    model_path,
)
print(f"模型已儲存至：{model_path}")



