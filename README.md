# elephant-flow-robustness

초반 N패킷만 보고 flow가 elephant(대용량 flow)인지 mice인지 예측하는 방법의 **견고성**을 분석하는 프로젝트입니다. 공개 백본 trace(MAWI)에서 flow 처음 몇 개의 데이터 패킷만으로 최종 크기를 얼마나 맞힐 수 있는지 재고, 그 결과가 날짜·데이터셋·임계값 정의가 바뀌어도 유지되는지 봅니다.

차별점은 평가 조건의 변화입니다. 본문을 확인한 범위([1]–[4], [7]–[9]; 문헌 목록과 한계는 `docs/problem.md` 7절)에서, 초반 패킷 기반 elephant 예측은 주로 한 trace 안에서 나눠 평가했습니다. 또 임계값을 정의별·크기별로 체계적으로 비교하지는 않은 것으로 보입니다. 이 프로젝트는 (1) 날짜 간·데이터셋 간 일반화와 (2) 임계값 정의·크기에 따른 민감도를 함께 봅니다. 다만 이 주장은 본문을 확인하지 못한 문헌([5], [6] 등)과 목록 밖 문헌을 포함하지 않으므로 "새롭다"고 단정하지 않습니다. 자세한 연구 질문은 `docs/problem.md` 8절에 있습니다.

## 현재 상태

최소 베이스라인 파이프라인이 구현되어 있습니다: 전처리(pcap → flow 표 CSV), 라벨·특징 생성, 학습·평가(RandomForest). 실제 MAWI 데이터로 돌린 결과는 아직 없습니다. 결과는 2026.12 E1–E3 이후 추가 예정입니다.

## 환경 설정

Python 3.11 이상이 필요합니다.

가상환경 생성과 활성화 (한 줄씩):

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# bash (Windows Git Bash). Linux/macOS는 .venv/bin/activate
python -m venv .venv
source .venv/Scripts/activate
```

의존성 설치:

```bash
pip install -r requirements.txt
```

의존성: dpkt, pandas, scikit-learn, pytest.

## 데이터

데이터는 MAWI(WIDE) Working Group Traffic Archive의 공개 pcap을 씁니다. 안내 페이지는 https://mawi.wide.ad.jp/mawi/ 입니다. 이 페이지에서 **samplepoint-F**의 pcap을 고릅니다. 파일 이름은 `YYYYMMDDHHMM.pcap.gz` 형식으로 문서화되어 있습니다. 정확한 디렉터리·파일 경로는 이 README를 쓸 때 확인하지 못했으므로 페이지에서 직접 확인해야 합니다.

받은 파일은 `data/raw/`에 둡니다. `data/`는 `.gitignore`에 있어 저장소에 올라가지 않습니다. CAIDA Anonymized Internet Traces는 데이터 사용 승인이 나지 않아 아직 쓰지 않습니다. 승인 후에 연결할 예정입니다.

필요한 폴더를 미리 만듭니다:

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force data/raw, data/processed, results
```

```bash
# bash
mkdir -p data/raw data/processed results
```

## 실행

모듈 실행은 프로젝트 루트에서 합니다. 이 프로젝트는 패키지로 설치하지 않으므로 `src/`를 import 경로에 넣어야 합니다. `pytest`는 `tests/`에서 `src/`를 직접 추가하므로 따로 설정할 필요가 없습니다.

```powershell
# Windows PowerShell
$env:PYTHONPATH = "src"
```

```bash
# bash (Windows Git Bash / Linux / macOS): 명령마다 앞에 붙입니다
PYTHONPATH=src python -m flowpred.preprocess ...
```

### 1. 전처리 (pcap → flow 표 CSV)

```
python -m flowpred.preprocess <pcap 경로> <출력 CSV 경로> [최대 패킷 수] [--sample-rate r]
```

예: 파일 앞부분 100만 패킷만 쓰기

```bash
PYTHONPATH=src python -m flowpred.preprocess data/raw/<파일>.pcap.gz data/processed/flows.csv 1000000
```

최대 패킷 수를 생략하면 파일 전체를 읽습니다. `.pcap`과 `.pcap.gz`를 모두 받습니다. 현재는 Ethernet 링크 타입만 지원합니다.

메모리가 모자라면 `--sample-rate r`(0 < r ≤ 1, 기본 1.0)로 flow를 해시 샘플링합니다. 방향 5-tuple의 crc32로 flow를 결정적으로 고르고, 고른 flow의 패킷은 전부 유지합니다. 출력 옆에 `<출력 CSV>.meta.json`(`{"sample_rate": r}`)도 씁니다. train은 이 파일을 읽어 결과 CSV의 `sample_rate` 열에 기록하고, train과 test의 sample_rate가 다르면 오류를 냅니다.

```bash
PYTHONPATH=src python -m flowpred.preprocess data/raw/<파일>.pcap.gz data/processed/flows.csv --sample-rate 0.1
```

2026-10-18 trace는 gz 6.1GB, 2.4억 패킷이라 샘플링 없이는 flow dict가 약 33GB 필요할 것으로 추정합니다(가정; 2012 trace 측정은 flow 258만 개에서 최대 4.8GB, 10.5분). 이 머신의 RAM은 15.6GB입니다. 샘플링해도 패킷은 전부 읽으므로 시간은 거의 줄지 않고 메모리가 줍니다. precision/recall/F1 같은 비율 지표는 영향이 없다고 보지만, table_reduction 같은 절대 규모 지표는 sample_rate로 나눠 해석해야 합니다.

### 2. 학습·평가

인자 이름은 `src/flowpred/train.py`의 `--help`와 같습니다. 학습 CSV만 필수 위치 인자입니다. `--test`를 주지 않으면 같은 CSV를 시작시각 순 70/30으로 나눕니다. 기본 `--n`은 4, 기본 임계값은 `bytes_pct` 0.01(train 바이트 상위 1%)입니다. 상위 10%는 데이터 패킷이 4개 미만인 elephant가 많아 정답이 특징에서 계산되는 누설 구조라 기본에서 뺐습니다(`docs/problem.md` 3.2.1).

기본 실행 (같은 CSV를 시간순 70/30으로 나눔):

```bash
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv
```

test CSV를 따로 주는 실행 (날짜·데이터셋 간 평가):

```bash
PYTHONPATH=src python -m flowpred.train data/processed/flows_day1.csv --test data/processed/flows_day2.csv
```

임계값을 패킷 수 상위 비율로 정하는 실행 (`--thr-param`은 `*_pct`에서 상위 비율 p, `bytes_fixed`에서는 바이트 값):

```bash
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv --thr-def pkts_pct --thr-param 0.01
```

train 행이 너무 많을 때 학습 행 수를 제한하는 실행 (`--train-max-rows`, 기본 전체):

```bash
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv --train-max-rows 500000
```

`--train-max-rows N`은 train이 N행보다 많으면 y 기준 층화 추출한 N행으로 학습합니다. 임계값은 전체 train으로 구하고 test는 줄이지 않습니다. 양성이 부족해 층화할 수 없으면 ValueError가 납니다. RandomForest는 `n_jobs=-1`로 학습합니다. 측정치(train 180만 행, n = 4 1회 41분, 최대 7GB)는 n_jobs 기본값 1일 때의 값입니다.

결과를 CSV에 누적 (실행마다 한 행이 추가되며, 파일이 없으면 헤더부터 씁니다. 결과 CSV는 26열입니다. 열이 바뀌었으므로 이전 열 수의 기존 파일에 이어 쓰지 말고 새 파일을 쓰세요):

```bash
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv --n 0 --out results/runs.csv
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv --n 4 --out results/runs.csv
```

PowerShell에서 `PYTHONPATH`를 설정했다면 `PYTHONPATH=src` 부분은 빼고 실행합니다.

### 테스트

```bash
python -m pytest -q
```

## 프로젝트 구조

```
network_pj/
├── docs/
│   ├── problem.md          문제정의, 확정값, 관련 연구, 연구 질문
│   └── design.md           파이프라인, 파일 형식, 실험 계획
├── src/
│   └── flowpred/
│       ├── __init__.py
│       ├── preprocess.py   pcap → flow 표 CSV
│       ├── features.py     시간순 분할, 임계값·라벨, 특징 행렬
│       └── train.py        RandomForest 학습, 주·보조 지표 출력, 결과 CSV 누적
├── tests/
│   ├── test_preprocess.py
│   ├── test_features.py
│   └── test_train.py
├── .gitignore
├── requirements.txt
└── README.md
```

문서: [docs/problem.md](docs/problem.md), [docs/design.md](docs/design.md)

## 평가 설정 요약

- flow: 단방향 5-tuple, IPv4 TCP/UDP. 전송 계층 페이로드가 0보다 큰 패킷만 "데이터 패킷"으로 셉니다.
- 예측 시점: 처음 N = 4개 데이터 패킷 (기본). N ∈ {0, 1, 3, 4, 10}을 비교 가능. N = 0은 헤더(proto·포트)만 쓰는 기준선.
- 특징: proto, src_port, dst_port, 처음 N개 데이터 패킷의 페이로드 크기와 도착 간격. IP 주소와 flow 종료 후 통계는 쓰지 않습니다.
- elephant: train 구간 바이트 수 상위 1%(상위 10%는 누설 대조군). test에는 train에서 구한 임계값을 그대로 적용합니다.
- 모델: RandomForest (분류, class_weight balanced) + RandomForest (회귀, log10 바이트 수).
- 지표: elephant 기준 precision, recall, F1, log10 바이트 MAE, 보조로 TNR, 트래픽 커버리지, flow table 감소 배수.

## 로드맵

- 2026.12: E1–E3 (기본 베이스라인, 헤더 전용 기준선, N ablation). MAWI trace 1개로 실행하고 결과를 README에 추가.
- 2027.01–03: R1–R4 (임계값 민감도, 날짜 간 일반화, 데이터셋 간 일반화(CAIDA 승인 시), 특징 기여). 자세한 내용은 `docs/design.md` 3.2절.

## 한계

- 15분 trace라 긴 flow는 잘립니다. trace 끝 근처에서 시작한 flow는 byte_count가 실제보다 작게 나올 수 있습니다. `--tail-sec` 옵션이 있지만 기본은 끄고 두며, 영향은 날짜 간 실험에서 따로 잽니다.
- trace 시작 전에 시작된 flow는 "처음 N개" 패킷이 실제 처음이 아닐 수 있습니다.
- IPv4 TCP/UDP만 다룹니다. IPv6, fragment, 그 밖의 프로토콜은 버립니다.
- flow는 한 pcap 파일 안에서만 묶습니다. idle timeout과 FIN/RST 기준 분리는 하지 않습니다.
- CAIDA는 아직 연결하지 않았습니다. 승인 전까지 일반화는 MAWI 날짜 간으로 제한됩니다.
- 단일 수집 지점이고 하루 15분씩만 봅니다. 날짜 간 차이의 원인을 단정할 수 없습니다.
- 문헌 중 일부([1-a], [5], [6])는 본문을 확인하지 못했습니다. 자세한 내용은 `docs/problem.md` 7.2절.
