# AI Archive Cleaner

[English](README.en.md)

AI Archive Cleaner は、Codex と Claude のローカルチャット履歴・生成物・一時ログを削除する Windows 向け GUI ツールです。

日本語環境では日本語UI、それ以外のOS言語では英語UIで起動します。

## 対応環境

- Windows 10 / 11
- ソースから起動する場合は Python 3.11 以降
- Codex App / Codex CLI のローカルファイル
- Claude Desktop / Claude Code / Claude CLI のローカルファイル

現在のリリースは Windows 専用です。macOS / Linux は、保存場所・プロセス制御・フォルダを開く処理が異なるため未対応です。

## 削除できるもの

一覧で選択して削除できるもの:

- Codex のチャット履歴
- Claude Code / Claude CLI の JSONL 履歴
- `Documents\Codex` 配下の生成物

選択したチャットやセッションを削除すると、対応するローカル索引・履歴行・関連メタデータも可能な範囲で掃除します。

共通ログ/キャッシュの削除を有効にすると、以下も削除します。

- Codex のログDB、TUIログ、sandboxログ
- Claude Code の `session-env` と `shell-snapshots`
- `AppData\Local\claude-cli-nodejs\Cache`
- Claude Desktop のログや一時的な Electron キャッシュ
  - `Cache`
  - `Code Cache`
  - `Crashpad`
  - `GPUCache`
  - `Shared Dictionary`

## 削除しないもの

- Codex / Claude の認証情報
- 主要設定ファイル
- Codex の `state_5.sqlite`
- Codex の `session_index.jsonl`
- Codex の `history.jsonl`
- プラグイン本体
- スキル本体
- Claude Desktop の `IndexedDB`
- Claude Desktop の `Local Storage`
- Claude Desktop の `Session Storage`
- Claude Desktop の `WebStorage`
- Claude Web のクラウド側チャット履歴
- Claude Memory

バックアップは作成しません。削除操作は自己責任で実行してください。

## 使い方

Release から `AIArchiveCleaner.exe` をダウンロードして起動してください。

ソースから起動する場合:

```powershell
python app.py
```

または `run.bat` を実行します。

## exe のビルド

```powershell
.\build_exe.ps1
```

出力先:

```text
dist\AIArchiveCleaner.exe
```

ビルドスクリプトは `.venv` を作成し、PyInstaller を仮想環境内にインストールします。グローバル環境にはインストールしません。

## 開発メモ

- 実行時の依存は Python 標準ライブラリのみです。
- ビルド時のみ PyInstaller を使います。
- `favicon.ico` はウィンドウアイコンと exe アイコンに使います。
- UI 言語は OS のロケールから自動判定します。

## ライセンス

MIT License. See [LICENSE](LICENSE).
