# 世界遺産 国あてクイズ

人気ランキングTOP50の世界遺産の画像から、どの国にあるかを国旗つきの4択で当てるクイズ。
GitHub Pages では `/heritage-quiz/` に公開される(ニュースダイジェストのデプロイに同乗)。

## ファイル
- `src/quiz.html` : ページ本体(CSS・国旗・イラスト・問題データ・動作)。`PHOTOS` に写真が入った問題は写真(複数なら横スクロールで切り替え)、それ以外はイラストを表示
- `sites.csv` : 50件の id・遺産名・Commons 検索キーワード
- `fetch_candidates.py` : Commons から写真候補を `candidates/<id>/<n>.jpg` と `candidates.csv` に保存(CC BY / CC BY-SA / CC0 / PD の横長JPEGのみ)
- `selection.csv` : 各遺産で使う候補番号を表示順に空白区切りで(人が見て選ぶ)
- `make_photos.py` : 選んだ候補(1遺産3枚)を `photos/<id>-<k>.jpg`(幅720px・品質68)と `photos/credits.csv` にする
- `build.py` : `dist/world-heritage-quiz.html`(写真埋め込みの1ファイル版)と `../public/heritage-quiz/`(Pages版)を出力

## 手順
1. 候補集め: Actions の「Heritage quiz photo candidates」を実行(`sites.csv` を変えて push しても動く)。結果は自動でコミットされる
2. `candidates/` を見て `selection.csv` に `id,n` を書く
3. `pip install pillow && python heritage-quiz/make_photos.py && python heritage-quiz/build.py`
