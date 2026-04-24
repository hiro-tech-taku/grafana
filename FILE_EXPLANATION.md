# grafana-local ファイル説明

## この構成で何をしているか

このフォルダは、ローカルで `Grafana` `Prometheus` `json-exporter` `mock-api` を Docker Compose で起動し、擬似的なメトリクスを Grafana で可視化するための構成です。

データの流れは次のとおりです。

1. `mock-api/app.py` が JSON 形式のメトリクスを返す
2. `json-exporter.yml` の設定に従って `json-exporter` が JSON を Prometheus 形式のメトリクスへ変換する
3. `prometheus.yml` の設定に従って Prometheus が `json-exporter` からメトリクスを収集する
4. `provisioning/datasources/datasource.yml` で Grafana が Prometheus をデータソースとして自動登録する
5. `provisioning/dashboards/dashboard.yml` と `sample-dashboard.json` で Grafana ダッシュボードを自動作成する

---

## ルート配下のファイル

### `docker-compose.yml`

このプロジェクトのメイン構成です。4 つのサービスを定義しています。

- `grafana`
  - Grafana 本体を起動します
  - `3000:3000` でホストからアクセスできます
  - 管理者ユーザー名とパスワードを環境変数で設定しています
  - `provisioning` 配下の YAML/JSON をコンテナ内にマウントし、起動時に自動反映します
- `prometheus`
  - Prometheus 本体を起動します
  - `9090:9090` でホストからアクセスできます
  - `prometheus.yml` を読み込んでスクレイプ設定を反映します
- `json-exporter`
  - JSON API を Prometheus が読めるメトリクス形式へ変換する中継役です
  - `7979:7979` で起動します
  - `json_exporter.yml` を `/config.yml` として読み込みます
- `mock-api`
  - 擬似メトリクスを返す Flask API です
  - `mock-api/Dockerfile` からビルドされ、`8080:8080` で公開されます

重要なポイント:

- `depends_on` により起動順の依存関係をある程度表現しています
- `grafana-storage` ボリュームは Grafana の状態保存用です
- 多くの設定ファイルが `:ro` でマウントされており、コンテナ内では読み取り専用です

### `Dockerfile`

Grafana 用の簡易 Dockerfile です。

内容:

- ベースイメージに `grafana/grafana:latest` を使う
- Grafana 管理者アカウント情報を環境変数で埋め込む
- `3000` 番ポートを公開する

このファイルは現在の `docker-compose.yml` では使われていません。`grafana` サービスは `build:` ではなく `image:` を使っているためです。将来、Grafana イメージを独自ビルドしたい場合の雛形として置かれている可能性があります。

### `prometheus.yml`

Prometheus の収集設定です。

#### `global`

- `scrape_interval: 15s`
  - 15 秒ごとにメトリクスを収集します

#### `scrape_configs`

- `job_name: 'prometheus'`
  - Prometheus 自身を監視しています
  - 対象は `prometheus:9090`
- `job_name: 'json_exporter'`
  - `json-exporter` 経由で JSON API を監視します
  - `metrics_path: /probe`
    - `json-exporter` のエンドポイントを叩きます
  - `params.module: [default]`
    - `json_exporter.yml` の `default` モジュールを使います
  - `static_configs.targets`
    - 実際の取得対象は `http://host.docker.internal:8080/metrics/json`
  - `relabel_configs`
    - Prometheus が最終的にアクセスする相手を `json-exporter:7979` に差し替えています
    - 元のターゲット URL は `__param_target` としてクエリパラメータに渡されます
    - `instance` ラベルにも元 URL を入れています

補足:

- `host.docker.internal` は Docker コンテナからホスト側へアクセスするための名前です
- この構成では `mock-api` も Compose 内にいるため、環境によっては `http://mock-api:8080/metrics/json` を直接使うほうが分かりやすい場合があります

### `json_exporter.yml`

`json-exporter` の変換ルールです。

`modules.default.metrics` に 4 つのメトリクス定義があります。

- `server_cpu_usage`
  - JSON の `cpu_usage` を数値メトリクスとして取り出す
- `server_memory_usage`
  - JSON の `memory_usage` を取り出す
- `server_disk_usage`
  - JSON の `disk_usage` を取り出す
- `server_status`
  - JSON の `status` を取り出す

各項目の意味:

- `name`
  - Prometheus 上で見えるメトリクス名
- `path`
  - JSONPath 風の記法で値を取り出す位置
- `help`
  - メトリクスの説明文
- `type: value`
  - 単純な数値として扱う指定

この設定により、`mock-api` が返す JSON を Prometheus が扱える時系列データへ変換できます。

### `docker-compose copy.yml`

バックアップまたは過去版と思われる Compose ファイルです。

`docker-compose.yml` との主な違い:

- `json-exporter` と `mock-api` サービスが存在しない
- `prometheus` は `json-exporter` を経由せず、自身のみを扱うシンプルな構成
- `prometheus.yml` のマウントに `:ro` が付いていない

現在の構成に比べると、Grafana + Prometheus の最小構成に近い内容です。

### `prometheus copy.yml`

Prometheus 設定の旧版またはサンプルです。

内容:

- コメントアウトされた `localhost:9090` 向け設定
- 実際に有効な `prometheus:9090` 向け設定

現在の `prometheus.yml` にある `json_exporter` 監視設定は含まれていません。こちらも最小構成から段階的に拡張した痕跡と見てよいです。

---

## `mock-api` 配下

### `mock-api/app.py`

Flask を使った簡単な API サーバーです。

#### `app = Flask(__name__)`

Flask アプリケーションを生成しています。

#### `@app.route("/metrics/json")`

`/metrics/json` にアクセスされたとき、以下の JSON を返します。

```json
{
  "cpu_usage": 42.5,
  "memory_usage": 68.2,
  "disk_usage": 71.9,
  "status": 1
}
```

この JSON が `json-exporter` の入力データです。

#### `@app.route("/")`

疎通確認用のエンドポイントです。

```json
{
  "message": "mock api is running"
}
```

#### `app.run(host="0.0.0.0", port=8080)`

- `0.0.0.0` で待ち受けることで、コンテナ外からもアクセス可能にしています
- ポートは `8080` を使用します

### `mock-api/Dockerfile`

`mock-api` サービス用イメージの定義です。

処理の流れ:

1. `python:3.12-slim` をベースに使う
2. 作業ディレクトリを `/app` にする
3. `flask` をインストールする
4. `app.py` をコピーする
5. `8080` ポートを公開する
6. `python app.py` で起動する

非常にシンプルで、検証用途の最小構成です。

---

## `provisioning` 配下

Grafana の `provisioning` は、起動時にデータソースやダッシュボードを自動登録する仕組みです。

### `provisioning/datasources/datasource.yml`

Grafana のデータソース自動登録設定です。

内容:

- `name: Prometheus`
  - Grafana 上の表示名
- `uid: prometheus`
  - ダッシュボード JSON から参照するための固定 ID
- `type: prometheus`
  - データソース種別
- `access: proxy`
  - Grafana サーバー経由で Prometheus に接続します
- `url: http://prometheus:9090`
  - Compose ネットワーク上の Prometheus サービス名で接続します
- `isDefault: true`
  - Grafana のデフォルトデータソースにします

### `provisioning/dashboards/dashboard.yml`

Grafana のダッシュボード自動登録設定です。

内容:

- `apiVersion: 1`
  - 設定フォーマットのバージョン
- `providers`
  - ダッシュボード供給元の設定
- `name: default`
  - プロバイダ名
- `orgId: 1`
  - Grafana の組織 ID
- `folder: Auto Provisioned`
  - Grafana UI 上で配置されるフォルダ名
- `type: file`
  - ファイルベースでダッシュボードを読み込む指定
- `disableDeletion: false`
  - ファイルが消えたら Grafana 側からも削除可能
- `updateIntervalSeconds: 10`
  - 10 秒ごとにファイル更新を監視
- `allowUiUpdates: true`
  - UI 上での編集を許可
- `options.path: /etc/grafana/provisioning/dashboards`
  - 読み込み対象のディレクトリ

この設定により、同ディレクトリ内の `sample-dashboard.json` が Grafana 起動後に自動で読み込まれます。

### `provisioning/dashboards/sample-dashboard.json`

Grafana ダッシュボードの本体です。

主な内容:

- タイトル: `Auto Provisioned Dashboard`
- UID: `auto-provisioned-dashboard`
- タグ: `auto`, `docker`
- 更新間隔: `10s`
- 表示期間: 直近 15 分

#### パネル 1: `Prometheus Targets Up`

- 種別: `timeseries`
- クエリ: `up`
- 凡例: `{{job}}`

`up` は Prometheus 標準メトリクスで、ターゲットが正常なら `1`、失敗なら `0` を返します。各ジョブの生死確認に使うパネルです。

#### パネル 2: `Process Start Time`

- 種別: `stat`
- クエリ: `process_start_time_seconds`

Prometheus プロセスの起動時刻を Unix 時刻で表示します。データソース側から取得できているかの確認には使えますが、検証ダッシュボードとしては少し分かりづらい値です。

補足:

- この JSON では、`json_exporter.yml` で作った `server_cpu_usage` などのメトリクスはまだ表示していません
- それらを可視化したい場合は、Grafana パネルのクエリに `server_cpu_usage` などを追加します

---

## ファイル同士の関係

構成上の対応関係をまとめると次のとおりです。

- `mock-api/app.py`
  - 元データとなる JSON を返す
- `json_exporter.yml`
  - JSON のどのキーをどのメトリクス名にするかを定義する
- `prometheus.yml`
  - `json-exporter` を通じてそのメトリクスを収集する
- `provisioning/datasources/datasource.yml`
  - Grafana から Prometheus へ接続する
- `provisioning/dashboards/dashboard.yml`
  - ダッシュボード JSON を Grafana に読み込ませる
- `provisioning/dashboards/sample-dashboard.json`
  - 実際に表示するグラフや統計パネルを定義する
- `docker-compose.yml`
  - これら全部をまとめて起動する

---

## 現状の確認ポイント

この構成を読むうえで、特に見ておくべき点は次の 3 つです。

- `Dockerfile` は現状未使用
  - `docker-compose.yml` が `image: grafana/grafana:latest` を使っているため
- `sample-dashboard.json` は `server_cpu_usage` などの自作メトリクスをまだ使っていない
  - 現状は `up` と `process_start_time_seconds` のみ表示
- `prometheus.yml` のターゲット URL に `host.docker.internal` を使っている
  - Docker ネットワーク内のサービス参照としては `mock-api:8080` のほうが構成意図に合う可能性がある

---

## 追加でやると理解しやすい改善

必要であれば次の改善もできます。

1. `FILE_EXPLANATION.md` を `README.md` として整理し直す
2. `sample-dashboard.json` に `server_cpu_usage` `server_memory_usage` `server_disk_usage` のパネルを追加する
3. `prometheus.yml` のターゲットを `mock-api:8080` に変更して、Compose 内通信に統一する
4. 未使用の `Dockerfile` と `copy` 系ファイルの扱いを整理する
