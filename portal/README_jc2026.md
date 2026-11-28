# うまミル ジャパンカップ 2026 版（2026-11-28 公開、Version 75）

公開先：https://claude.ai/artifact/2Z5PcZzdtBLifGUjvwGXJe

1. 明日の全24レースのAI勝率：仮想ベットのコード（claude/project-thread-6gor0u の `python3 -m live bet --date 2026-11-29`）を
   `KEIBA_SHARED=<スクラッチ>` で実行（共有の betting/ の記録には書かない）→ predictions/2026-11-29.csv
2. `python3 portal/fetch_card.py 202605050812`（東京の馬場は JRA の index.html。fetch_card.py を競馬場コードで切り替えるよう修正）、
   ほかのレースは `--no-baba`
3. 予想パイプライン（keiba-sim/pipeline の update.py → predict.py 2026-11-29 202605050812、10万回）→ `portal/jc_sim.csv`（展開シミュの列）
4. `theater/tools/build_field.py --predictions portal/jc_field_preds.csv --date 2026-11-29 --venue 東京 --surface 芝 --distance 2400 --past ジャパンC`
   → `node theater/tools/calibrate.mjs theater/data/jc2026.field.json theater/data/jc2026.json`
5. `python3 portal/build.py --featured theater/data/jc2026.json --sim portal/jc_sim.csv --wet /nonexistent --today <1のcsv>`
6. `python3 portal/make_odds.py 2026-11-29`、`cd portal && python3 fetch_combos.py 2026-11-29`

修正：scraper/parse.py の出馬表パースで、馬番10〜18が斤量として読まれていた（"58.0" 形式を優先するよう修正）。
公開ファイル数の上限（511）に近いので、過去の菊花賞・エリザベス女王杯・マイルCSの過去レースと古いオッズを公開ファイルから外した。
