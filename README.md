# keiba-sim

過去のレースデータから各馬の能力を推定し、簡易的にモデル化したコースで馬を
実際に何千回も走らせて、勝率・複勝率を予想するシミュレーターです。
目標は2026年の菊花賞（京都 芝3000m）の予想です。

## いまできること

- 京都 芝3000m（外回り）のコースモデル：コーナー、直線、3コーナーの坂（2回通過）
- レースシミュレーション（`sim/race.py`）：各馬がスピード・スタミナ・瞬発力・脚質・馬番を持ち、
  ペース、スタミナ消費、坂、コーナーの外回りロス、前が詰まる・後ろにつけて脚をためる、を再現
- モンテカルロで勝率・複勝率・平均着順を計算
- ブラウザでレースを再生するアプリ（`web/`）

デモは架空の馬にランダムな能力値を与えたもので、実際の予想ではありません。

## 使い方

```bash
pip install -r requirements.txt
python3 scripts/demo.py          # web/data/demo.json を作る
python3 -m unittest              # テスト
cd web && python3 -m http.server # http://localhost:8000 で表示
```

`web/` はそのまま Cloudflare Pages に置ける静的サイトです。
別のレースは `web/data/<名前>.json` に置き、`?race=<名前>` で表示します。

## 予想モデル（`predict/`）

過去走から作った特徴量で、同じレースの馬どうしを比べて勝率を出します。numpy と pandas だけで動きます。
改善の経緯と結果は `reports/pdca.md` にあります。

- `predict/data.py`：SQLite（`data/keiba.sqlite`、`--db` か環境変数 `KEIBA_DB` で変更可）を読み取り専用で開く
- `predict/features.py`：レース当日より前の走りだけを使った特徴量（スピード指数、上がり、着順、賞金、騎手・調教師の成績、距離変更、間隔など）
- `predict/model.py`：条件付きロジット（ニュートン法 + L2）。比較用の線形モデル
- `predict/gbm.py`：レース内ソフトマックスを損失にした勾配ブースティング木（本命モデル）
- `predict/pipeline.py`：乱数違いの木3本の平均。オッズなしの能力モデルと、確定オッズを補正する市場補正モデル
- `predict/evaluate.py`：logloss、1番手の勝率・複勝率、単複の回収率

```bash
# 日付で学習(〜2024) / 検証(2025) / テスト(2026〜) に分けて評価 → reports/backtest.md
python3 scripts/backtest.py --db data/keiba.sqlite --valid-start 2025-01-01 --test-start 2026-01-01

# 出走予定馬の勝率 → reports/kikka2026.md
python3 scripts/predict_race.py races/kikka2026.csv --db data/keiba.sqlite --date 2026-10-25 --name 第87回菊花賞 --out reports/kikka2026.md
```

データが増えたら同じコマンドを再実行するだけです。`races/kikka2026.csv` は登録・枠順が出たら更新します
（`number`、`weight_carried` 列を足すとそれも使い、全頭の `odds` を入れると市場補正後の勝率も出します）。

## 計画

1. データ収集：過去10年ほどのJRAのレース結果・馬・血統・騎手・オッズ・タイム
2. 能力値の推定：過去の走りから各馬のスピード・スタミナ・瞬発力・脚質を推定
3. 検証：年で学習用とテスト用に分けて実際の着順と比べ、馬券の買い方ごとの回収率も確認
4. 公開：Cloudflare Pages。菊花賞の枠順確定後に予想を更新
