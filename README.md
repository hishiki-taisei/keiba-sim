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

## 計画

1. データ収集：過去10年ほどのJRAのレース結果・馬・血統・騎手・オッズ・タイム
2. 能力値の推定：過去の走りから各馬のスピード・スタミナ・瞬発力・脚質を推定
3. 検証：年で学習用とテスト用に分けて実際の着順と比べ、馬券の買い方ごとの回収率も確認
4. 公開：Cloudflare Pages。菊花賞の枠順確定後に予想を更新

## 予想サイトの試作版（`portal/`）

初心者向けの「かんたん」と上級者向けの「くわしく」を切り替えられる予想サイトです。
DBを読み出し専用で開き、予想モデルのコードは読み込みません（予想はCSVから読みます）。

```bash
python3 portal/build.py --db /mnt/project-files/keiba-sim/data/keiba.sqlite \
    --predictions /mnt/project-files/keiba-sim/predictions/kikka2026_preliminary.csv
cd portal/www && python3 -m http.server   # http://localhost:8000
```

- 菊花賞2026（出走予定馬）、直近2開催日の全レース、過去の菊花賞を `portal/www/data/` に書き出します（`--days` で日数を変更）
- 画面：予想（確率順のカードと根拠の文章）／出馬表（並べ替え・列の切替・期待値）／コース傾向／印と買い目（結果の答え合わせ）／結果
- 近走・騎手・種牡馬・コース傾向の数字は、そのレースの日より前のレースだけで集計しています
