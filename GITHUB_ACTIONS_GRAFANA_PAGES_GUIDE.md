# GitHub Actions + Docker Compose + GitHub Pages 自動化手順

## 結論

`grafana-local` の `docker-compose.yml` を GitHub Actions でビルドし、そのまま **GitHub Pages 上で Grafana を動かすことはできません**。

理由は以下です。

- GitHub Pages は **静的サイトホスティング** であり、HTML/CSS/JavaScript などの静的ファイルを公開する仕組みです。
- GitHub Actions の `ubuntu-latest` ランナー上では `docker compose` を実行できますが、ジョブ終了後にランナーは破棄されるため、Grafana コンテナを常駐させるデプロイ先にはなりません。

そのため、実現パターンは次のいずれかになります。

1. **推奨構成**
   GitHub Actions で Docker Compose のビルドと疎通確認を行い、Grafana は EC2 / VPS / Azure VM / 自宅サーバー / self-hosted runner などの常駐サーバーへデプロイし、GitHub Pages には説明ページやリンク集を公開する。
2. **GitHub Pages だけで見せたい構成**
   GitHub Actions で Grafana のダッシュボード画像や静的 HTML を生成し、それを GitHub Pages に公開する。
3. **外部公開された Grafana を Pages から見せる構成**
   外部ホスト上の Grafana を公開し、GitHub Pages 側には埋め込み用ページや導線ページを置く。

このドキュメントでは、最も現実的な **推奨構成** を中心に整理します。

---

## 前提整理

現在の `docker-compose.yml` では、次の 4 サービスが起動します。

- `grafana`
- `prometheus`
- `json-exporter`
- `mock-api`

また、現在の `.github/workflows/deploy-pages.yml` は、リポジトリ内容をそのまま GitHub Pages にアップロードするだけであり、次の処理は実行していません。

- `docker compose build`
- `docker compose up`
- コンテナのヘルスチェック
- 外部サーバーへのデプロイ

---

## 実現したい自動化の全体像

### 1. CI: GitHub Actions で Docker Compose を検証

`main` への push または pull request を契機に GitHub Actions を実行し、以下を自動化します。

- リポジトリを checkout
- `docker compose build`
- `docker compose up -d`
- `mock-api` / `json-exporter` / `prometheus` / `grafana` の起動確認
- 必要なら API 応答や Prometheus scrape の確認
- テスト完了後に `docker compose down`

この段階は **ビルド・テスト用途** であり、本番公開先ではありません。

### 2. CD: 常駐サーバーへデプロイ

Grafana を実際に表示し続けるには、GitHub Actions から以下のいずれかにデプロイします。

- VPS
- クラウド VM
- self-hosted runner を置いた Linux サーバー
- Docker が常駐する自前ホスト

デプロイ方式の例:

- SSH でサーバーへ入り `git pull && docker compose up -d --build`
- Docker image を GitHub Container Registry に push して、サーバー側で pull
- self-hosted runner 上で直接 `docker compose up -d`

### 3. Pages: GitHub Pages には静的ページを公開

GitHub Pages には以下のいずれかを公開します。

- Grafana 本体へのリンクページ
- システム概要ページ
- 埋め込み用 HTML
- ダッシュボードの静的スクリーンショット
- 運用手順や README サイト

---

## 必要な手順

## 手順 1. まず要件を確定する

最初に、どの表示形態を目指すかを決めます。

### パターン A: Live な Grafana を見せたい

必要です。

- GitHub Actions による CI
- 外部サーバーへのデプロイ
- GitHub Pages は補助ページとして利用

### パターン B: GitHub Pages 上で見えることだけが重要

必要です。

- GitHub Actions による Compose 起動
- Grafana から画像や静的成果物を生成
- 生成物を Pages に publish

### パターン C: Pages から Grafana を開ければよい

必要です。

- Grafana 本体は別ホストで公開
- Pages にはリンクまたは埋め込みページを配置

---

## 手順 2. GitHub Actions の責務を 2 つに分ける

ワークフローは、少なくとも次の 2 系統に分けるのが扱いやすいです。

### `ci-compose.yml`

目的:

- Docker Compose のビルド検証
- コンテナ起動確認
- 設定ファイル変更時の破壊検知

主な流れ:

1. `actions/checkout@v4`
2. `docker compose build`
3. `docker compose up -d`
4. `curl` などでサービス疎通確認
5. ログ採取
6. `docker compose down -v`

### `deploy-pages.yml`

目的:

- GitHub Pages 用の静的ファイルを作って publish

主な流れ:

1. `actions/checkout@v4`
2. 静的ページ生成
3. `actions/configure-pages@v5`
4. `actions/upload-pages-artifact@v3`
5. `actions/deploy-pages@v4`

注意:

Pages ワークフローでは **Grafana コンテナをホスティングしません**。Pages に渡すのはあくまで静的成果物です。

---

## 手順 3. CI 用ワークフローを作る

以下のような確認を自動化します。

### 確認項目

- `docker compose config` が通る
- `mock-api` が `http://localhost:8080` で応答する
- `json-exporter` が `http://localhost:7979` で応答する
- `prometheus` が `http://localhost:9090/-/healthy` で応答する
- `grafana` が `http://localhost:3000/api/health` で応答する

### 実装イメージ

```yaml
name: CI Compose

on:
  push:
    branches: [main]
  pull_request:

jobs:
  compose-test:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Validate compose
        run: docker compose config

      - name: Build containers
        run: docker compose build

      - name: Start containers
        run: docker compose up -d

      - name: Wait for services
        run: |
          sleep 20
          curl -f http://localhost:8080
          curl -f http://localhost:7979
          curl -f http://localhost:9090/-/healthy
          curl -f http://localhost:3000/api/health

      - name: Show logs on failure
        if: failure()
        run: docker compose logs --no-color

      - name: Stop containers
        if: always()
        run: docker compose down -v
```

---

## 手順 4. Grafana の本番配置先を決める

GitHub Pages では Grafana 本体は動かせないため、常駐先が必要です。

### 選択肢 1: Linux サーバーに SSH デプロイ

構成:

- GitHub Actions で build/test
- 成功後、SSH で本番サーバー接続
- サーバー側で `docker compose up -d --build`

必要な準備:

- 公開サーバー
- Docker / Docker Compose
- リポジトリ取得用の鍵またはデプロイ方式
- GitHub Secrets
  - `SSH_HOST`
  - `SSH_USER`
  - `SSH_PRIVATE_KEY`

### 選択肢 2: self-hosted runner 上で直接デプロイ

構成:

- 本番サーバー自体を self-hosted runner にする
- GitHub Actions がそのサーバー上で `docker compose up -d` を実行

利点:

- SSH スクリプトを簡略化しやすい

注意:

- runner と本番環境が同居するため、権限設計とセキュリティ管理が必要

### 選択肢 3: コンテナレジストリ経由

構成:

- GitHub Actions で image build
- GitHub Container Registry へ push
- 本番サーバーが image を pull

利点:

- デプロイを再現しやすい
- `mock-api` を独立 image として管理しやすい

---

## 手順 5. 本番デプロイ用の secrets を用意する

GitHub リポジトリの `Settings > Secrets and variables > Actions` に最低限以下を用意します。

- `GF_SECURITY_ADMIN_USER`
- `GF_SECURITY_ADMIN_PASSWORD`
- `SSH_HOST`
- `SSH_USER`
- `SSH_PRIVATE_KEY`

必要に応じて追加します。

- `GRAFANA_DOMAIN`
- `PROMETHEUS_TARGET`
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `GHCR_TOKEN`

注意:

- 現在の `docker-compose.yml` では Grafana の管理者 ID とパスワードが固定値です。
- 本番運用では直書きをやめ、環境変数または `.env` に切り分けるべきです。

---

## 手順 6. 本番用 compose 構成を分離する

ローカル検証用と本番用を完全に同一にすると、運用で困ることが多いです。

推奨構成:

- `docker-compose.yml`
  - 共通定義
- `docker-compose.prod.yml`
  - 本番用 override
- `.env.example`
  - 必須環境変数の雛形

本番用で見直す項目:

- `image: latest` を固定タグへ変更
- `container_name` の固定化を必要最小限にする
- 永続ボリュームの保存先
- Grafana の管理者パスワード
- 公開ポート
- リバースプロキシの有無
- HTTPS 終端

---

## 手順 7. GitHub Actions から本番サーバーへデプロイする

SSH デプロイの典型フローは以下です。

1. `main` への push で CI 成功
2. Deploy ジョブ開始
3. 秘密鍵を設定
4. SSH で本番サーバーへ接続
5. リポジトリ更新
6. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
7. ヘルスチェック

実装イメージ:

```yaml
name: Deploy Production

on:
  workflow_dispatch:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup SSH key
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.SSH_PRIVATE_KEY }}" > ~/.ssh/id_rsa
          chmod 600 ~/.ssh/id_rsa
          ssh-keyscan -H ${{ secrets.SSH_HOST }} >> ~/.ssh/known_hosts

      - name: Deploy to server
        run: |
          ssh ${{ secrets.SSH_USER }}@${{ secrets.SSH_HOST }} '
            cd /opt/grafana-local &&
            git pull &&
            export GF_SECURITY_ADMIN_USER=${{ secrets.GF_SECURITY_ADMIN_USER }} &&
            export GF_SECURITY_ADMIN_PASSWORD=${{ secrets.GF_SECURITY_ADMIN_PASSWORD }} &&
            docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
          '
```

---

## 手順 8. GitHub Pages 側の役割を決める

GitHub Pages に何を載せるかを明確にします。

### 案 1: ランディングページを載せる

表示内容の例:

- システム説明
- Grafana 本体へのリンク
- ダッシュボード一覧
- 更新日時

最も安全で実装が簡単です。

### 案 2: 外部公開された Grafana の埋め込みページを載せる

前提:

- Grafana 側で匿名閲覧または外部共有設定が必要
- 共有 URL を iframe で埋め込めること

注意:

- 認証付き Grafana は単純埋め込みしにくい
- セキュリティヘッダや `X-Frame-Options` / CSP 次第で埋め込み不可のことがある

### 案 3: 静的な画像やスナップショットを載せる

向いているケース:

- 「Live でなくてよい」
- GitHub Pages だけで完結したい

生成方法の例:

- Grafana の共有機能でスナップショットを作る
- Image Renderer を使って PNG を生成する
- 生成した画像を Pages に配置する

---

## 手順 9. GitHub Pages 用 workflow を修正する

現在の `deploy-pages.yml` はリポジトリ全体をそのまま Pages に上げています。これを、**静的サイト生成物だけをデプロイする構成** に変更します。

想定ディレクトリ例:

- `site/`
  - `index.html`
  - `assets/`
  - `dashboards/`

Pages 用 workflow の考え方:

1. `site/` を生成または更新
2. `actions/configure-pages@v5`
3. `actions/upload-pages-artifact@v3` で `site/` をアップロード
4. `actions/deploy-pages@v4`

実装イメージ:

```yaml
name: Deploy GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build-pages:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Prepare static site
        run: |
          mkdir -p site
          cp -r docs/* site/ 2>/dev/null || true

      - name: Configure Pages
        uses: actions/configure-pages@v5

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build-pages
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

---

## 手順 10. Pages に載せる `index.html` を作る

最低限、以下があると運用しやすくなります。

- Grafana 本体 URL
- 説明文
- 最終デプロイ日時
- GitHub リポジトリ URL
- 障害時の案内

もし Pages を「ダッシュボードの入口」として使うなら、`index.html` は以下のような役割にすると整理しやすいです。

- 概要
- ダッシュボードへのリンク
- 更新ステータス
- スクリーンショット

---

## 手順 11. 必要なら Grafana の静的成果物を生成する

GitHub Pages だけでダッシュボードを見せたいなら、Grafana の live UI ではなく成果物化が必要です。

候補:

- PNG 画像
- PDF
- スナップショットリンク
- 外部共有リンク

この場合の流れ:

1. Actions で Compose 起動
2. Grafana API または共有機能で成果物生成
3. `site/` に配置
4. Pages に publish

注意:

- 画像生成は Grafana の Image Renderer 構成が必要になることがあります。
- 共有リンクや external share は公開範囲の設計が必要です。

---

## 手順 12. 運用面を固める

最低限、以下を決めてください。

- 本番の公開 URL
- 認証方式
- HTTPS の終端位置
- データ永続化場所
- バックアップ方法
- 更新時のロールバック手順
- 監視対象

とくに現在の構成では、`grafana-storage` だけが永続化対象なので、本番でどこに保存するかを明確にする必要があります。

---

## 推奨する最終構成

最も現実的なのは次の構成です。

### CI

- GitHub Actions
- `docker compose build`
- `docker compose up -d`
- ヘルスチェック

### CD

- 本番 Linux サーバーへ SSH デプロイ
- または self-hosted runner で直接デプロイ

### 公開

- Grafana 本体は外部サーバーで常駐公開
- GitHub Pages は案内ページまたは埋め込みページを配信

---

## このリポジトリで次にやるべき作業

優先度順に並べると以下です。

1. `deploy-pages.yml` を Pages 専用の静的配信用に修正する
2. `ci-compose.yml` を新規追加して Compose の起動確認を自動化する
3. `docker-compose.prod.yml` を作成して本番差分を分離する
4. Grafana 管理者情報を Secrets 化する
5. 本番配置先を決める
6. SSH もしくは self-hosted runner ベースの deploy workflow を追加する
7. Pages に置く `index.html` または `docs/` を作る

---

## 参考情報

- GitHub Pages は静的サイトホスティング: https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages
- GitHub Pages の公開元設定: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- GitHub Pages の deploy action: https://github.com/actions/deploy-pages
- GitHub-hosted runner の仕様: https://docs.github.com/actions/reference/runners/github-hosted-runners
- Grafana の Docker 実行: https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/
- Grafana の共有・スナップショット・埋め込み: https://grafana.com/docs/grafana/latest/dashboards/share-dashboards-panels/
- Grafana Image Renderer: https://grafana.com/docs/grafana/latest/setup-grafana/image-rendering/
