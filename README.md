# elephant-flow-robustness

초반 N패킷만 보고 flow가 elephant(대용량 flow)인지 mice인지 예측하는 방법의 **견고성**을 분석하는 프로젝트입니다. 공개 백본 trace(MAWI)에서 flow 처음 몇 개의 데이터 패킷만으로 최종 크기를 얼마나 맞힐 수 있는지 재고, 그 결과가 날짜·데이터셋·임계값 정의가 바뀌어도 유지되는지 봅니다.

차별점은 평가 조건의 변화입니다. 본문을 확인한 범위([1]–[4], [7]–[9]; 문헌 목록과 한계는 `docs/problem.md` 7절)에서, 초반 패킷 기반 elephant 예측은 주로 한 trace 안에서 나눠 평가했습니다. 또 임계값을 정의별·크기별로 체계적으로 비교하지는 않은 것으로 보입니다. 이 프로젝트는 (1) 날짜 간·데이터셋 간 일반화와 (2) 임계값 정의·크기에 따른 민감도를 함께 봅니다. 다만 이 주장은 본문을 확인하지 못한 문헌([5], [6] 등)과 목록 밖 문헌을 포함하지 않으므로 "새롭다"고 단정하지 않습니다. 자세한 연구 질문은 `docs/problem.md` 8절에 있습니다.

## 현재 상태

최소 베이스라인 파이프라인이 구현되어 있습니다: 전처리(pcap → flow 표 CSV), 라벨·특징 생성, 학습·평가(RandomForest). MAWI 2012-04-09 trace 1개로 E1–E3를 돌린 예비 결과가 아래 "예비 결과"에 있습니다. 날짜 간(2012 ↔ 2026) 예비 결과는 "날짜 간 예비 결과" 절에 있고, 데이터셋 간(CAIDA) 결과는 아직 없습니다.

## 예비 결과 (MAWI 2012-04-09, trace 1개)

설정: 258만 flow, 시간순 70/30 분할, 임계값 = train 상위 1% (34,911 B), test elephant 6,982개, 기본 RandomForest. n = 3, 4, 10은 시드 5개(0–4) 평균, n = 0, 1은 시드 0 하나. F1 CI는 test flow 복원추출 200회(95%)의 평균 구간입니다.

| n | F1 | 시드 간 표준편차 | F1 95% CI | precision | recall | recall(long) | short elephant 비율 |
|---|---|---|---|---|---|---|---|
| 0 (헤더만) | 0.166 | - | 0.160–0.171 | 0.109 | 0.342 | 0.342 | 0 |
| 1 | 0.457 | - | 0.447–0.468 | 0.459 | 0.454 | 0.455 | 0.000 |
| 3 | 0.656 | 0.0020 | 0.647–0.666 | 0.759 | 0.578 | 0.587 (시드 0) | 0.009 |
| 4 | 0.677 | 0.0015 | 0.667–0.686 | 0.782 | 0.597 | 0.602 (시드 0) | 0.010 |
| 10 | 0.754 | 0.0014 | 0.747–0.763 | 0.793 | 0.719 | 0.731 (시드 0) | 0.013 |

- n이 커질수록 F1이 오릅니다. 헤더만 쓴 기준선(n = 0)과 n = 4 사이 차이가 가장 큽니다.
- n = 3과 n = 4의 F1 차이(0.020)는 시드 변동(표준편차 약 0.002)보다 크지만, test 표본 변동을 보는 부트스트랩 평균 CI는 거의 맞닿지만 겹치지 않고(0.666 대 0.667), 시드 0끼리의 구간은 약간 겹칩니다.
- 누설 구조(데이터 패킷이 n개 미만인데 elephant인 flow)는 전체 elephant의 1.3% 이하입니다.
- 한계: trace 1개, 단일 날짜입니다. 날짜가 바뀔 때의 변동은 이 숫자에 들어 있지 않습니다. 날짜 간 일반화(R2)와 임계값 민감도(R1)는 후속 실험입니다.

### 최신 trace (MAWI 2026-10-14, 같은 설정, 시드 0 하나)

flow 401만 개(`--sample-rate 0.1`), train 281만 / test 120만, 임계값 = train 상위 1% (8,994 B), test elephant 11,662개. 같은 trace를 시간순 70/30으로 나눈 결과이며 날짜 간 일반화가 아닙니다.

| n | F1 | F1 95% CI | precision | recall | short elephant 비율 |
|---|---|---|---|---|---|
| 0 (헤더만) | 0.276 | 0.269–0.283 | 0.233 | 0.339 | 0 |
| 1 | 0.389 | 0.380–0.398 | 0.427 | 0.358 | 0.000 |
| 3 | 0.613 | 0.606–0.621 | 0.777 | 0.506 | 0.007 |
| 4 | 0.683 | 0.676–0.691 | 0.820 | 0.585 | 0.017 |
| 10 | 0.864 | 0.860–0.869 | 0.924 | 0.812 | **0.237** |

- n = 10의 F1은 비교하면 안 됩니다. test elephant의 23.7%가 데이터 패킷 10개 미만이라 정답이 특징에 그대로 들어 있습니다(2012는 1.3%). 임계값이 낮아서 생긴 차이입니다.
- n = 4의 F1은 2012(0.677)와 비슷하지만, 각각 한 trace 안에서 나눈 값이라 일반화를 뜻하지 않습니다.
- n = 0(헤더만)의 F1이 2012(0.166)보다 높습니다. 원인은 확인하지 않았습니다.
- 두 trace는 임계값 값(34,911 B 대 8,994 B)이 달라 같은 "상위 1%"라도 같은 대상이 아닙니다. 절대 규모 지표는 `sample_rate`로 보정해서 봐야 합니다.

## 날짜 간 예비 결과 (R2: MAWI 2012-04-09 ↔ 2026-10-14)

두 trace 모두 `--sample-rate 0.1`(같은 비율이 필요합니다). 학습 flow는 25.7만 개로 맞췄습니다(2026 쪽은 `--train-max-rows 257036`). **임계값은 8,909 B로 두 방향 모두 같습니다**(2026에서 구한 값, 2012 → 2026 쪽은 `--thr-fit test`). n = 4의 날짜 간 두 열만 시드 5개 평균 ± 표준편차이고, 나머지 칸은 시드 0 하나입니다. 2026 안 열의 임계값은 8,994 B(train 70%에서 구함)입니다. 2012 → 2026 쪽의 `--thr-fit test`는 test 쪽 분포로 임계값을 구하는 설정이라 실제 배포 조건보다 유리합니다.

| n | 2012 → 2026 F1 | 2026 → 2012 F1 | 2026 안 (학습 크기 맞춤) F1 |
|---|---|---|---|
| 0 | 0.137 | 0.078 | 0.230 |
| 1 | 0.182 | 0.319 | 0.352 |
| 3 | 0.202 | 0.368 | 0.546 |
| 4 | **0.290 ± 0.006** (recall 0.18) | **0.635 ± 0.016** (recall 0.50) | 0.611 |
| 10 | 0.702 (short elephant 23.2%, 부풀려짐) | 0.890 (short 11.0%, 부풀려짐) | 0.805 (short 23.7%) |

- 같은 날짜 안에서 학습·평가할 때(n = 4, F1 0.61–0.68)보다 날짜 간 성능이 떨어지고, **방향에 따라 다릅니다.** 2012로 학습해 2026을 맞출 때(0.29)가 2026으로 학습해 2012를 맞출 때(0.64)보다 훨씬 낮습니다. 시드 표준편차(0.006–0.016)는 이 격차(0.35)보다 훨씬 작습니다.
- 주의: test 양성 비율이 다릅니다(2026 test 1.0%, 2012 test 1.9%). F1은 양성 비율에 민감하므로 이 격차의 일부는 그 때문일 수 있습니다. recall(0.18 대 0.50, 시드 5개 평균)도 같은 방향입니다. 단, n = 0(헤더만)에서는 반대로 2012 → 2026이 더 높습니다(0.137 대 0.078, 시드 1개). 비대칭은 n ≥ 1에서만 보입니다.
- 임계값 효과: 2012에서 구한 임계값(33,472 B)을 2026에 그대로 쓰면 2026의 양성이 0.35%로 줄고 n = 4 F1이 0.029까지 내려갑니다(시드 5개 평균, 표준편차 0.003). 위 표는 두 방향에 같은 임계값을 써서 이 불일치를 없앤 값입니다. 다만 train 쪽 양성 비율은 여전히 다릅니다(2012 train 1.9%, 2026 train 1.0%).
- 학습 크기 효과: 2026 안에서 학습을 281만 → 25.7만 flow로 줄이면 n = 4 F1이 0.683에서 0.611로 내려갑니다(시드 1개).
- 프로토콜별 recall (n = 4, 임계값 8,909 B, 시드 5개, `recall_tcp`/`recall_udp`는 표준 출력에만 나옴): 2012 → 2026은 TCP elephant 0.22–0.23, UDP elephant 0.06–0.11입니다(2026 elephant의 30%가 UDP). 2026 → 2012는 TCP 0.51–0.56, UDP 0.00입니다(2012 elephant의 7%가 UDP). UDP elephant는 양방향 모두 거의 못 맞히지만, 2012 → 2026은 TCP만 봐도 recall이 0.53에서 0.22로 떨어집니다. 그래서 "학습 trace에 UDP elephant가 적어서"만으로는 격차가 설명되지 않습니다. 2012 임계값(33,472 B)을 쓰면 TCP 0.02, UDP 0.00입니다(시드 0).
- 아직 모르는 것: 비대칭의 원인(가설: 2026 트래픽이 더 다양하다), 시간 차이인지 수집 환경 차이인지. trace가 두 개뿐이라 구분할 수 없습니다. 특징 분포 비교와 다른 연도 추가가 필요합니다.

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
python -m flowpred.preprocess <pcap 경로> <출력 CSV 경로> [최대 패킷 수] [--sample-rate r] [--checkpoint PATH] [--every N]
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

몇 시간 걸리는 큰 trace는 `--checkpoint PATH`로 중간 상태를 저장하게 합니다. `--every N`(기본 20,000,000)패킷마다 stderr에 진행 줄(읽은 패킷 수, flow 수, 경과 초)을 쓰고 `PATH`에 flow 상태를 저장합니다. 도중에 죽으면 **같은 명령을 다시 실행**하면 `PATH`부터 이어가고(앞쪽 패킷은 파싱 없이 건너뜀), 정상 종료하면 `PATH`를 지웁니다. 이어받을 때 `--sample-rate`나 pcap 파일 크기 등이 체크포인트와 다르면 오류를 냅니다. 체크포인트 파일은 flow 수만큼 커집니다.

```bash
PYTHONPATH=src python -m flowpred.preprocess data/raw/<파일>.pcap.gz data/processed/flows.csv --sample-rate 0.1 --checkpoint data/processed/flows.ckpt
```

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

결과를 CSV에 누적 (실행마다 한 행이 추가되며, 파일이 없으면 헤더부터 씁니다. 결과 CSV는 32열입니다. 맨 끝 3열 `seed`, `f1_lo`, `f1_hi`는 `--seed` 값과 F1 부트스트랩 95% 신뢰구간입니다(아래 설명). 그 앞 3열 `el_short_frac`, `recall_long`, `recall_short`는 test elephant를 `n_seen` < n(short)과 그 외(long)로 나눈 비율과 그룹별 recall이며, 분모가 0이면 빈 값(N/A)이고 n = 0이면 `el_short_frac` = 0, `recall_short`는 빈 값입니다. 열이 바뀌었으므로 이전 열 수의 기존 파일에 이어 쓰지 말고 새 파일을 쓰세요):

```bash
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv --n 0 --out results/runs.csv
PYTHONPATH=src python -m flowpred.train data/processed/flows.csv --n 4 --out results/runs.csv
```

`--seed S`(기본 0)는 RandomForest 분류기·회귀기의 `random_state`와 `--train-max-rows` 층화 추출의 `random_state`에 쓰입니다. 기본 0은 이전 동작과 같습니다. F1 신뢰구간(`f1_lo`, `f1_hi`)은 test flow를 복원추출하는 일을 200회 반복해 매번 F1을 계산하고 2.5, 97.5 백분위수를 취한 값이며, 복원추출 표본에 양성이 없으면 그 반복의 F1은 0, test 양성이 0개면 빈 값(N/A)입니다. 부트스트랩 난수도 같은 `--seed`로 고정됩니다. 구간은 test 표본 변동만 보여 주므로, 모델 시드에 따른 변동은 `--seed`를 바꿔 반복 실행해서 확인하세요.

표준 출력에는 `el_udp_frac`(UDP elephant 비율), `recall_tcp`, `recall_udp`(프로토콜별 recall) 한 줄도 나옵니다. 해당 elephant가 없으면 N/A입니다. 결과 CSV 열은 아니므로(32열 그대로) 필요하면 출력을 따로 저장하세요.

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
│   ├── design.md           파이프라인, 파일 형식, 실험 계획
│   └── project-map.html    프로젝트 구조도 (브라우저로 열기)
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

- 2026.12: E1–E3 (기본 베이스라인, 헤더 전용 기준선, N ablation). MAWI trace 1개로 실행하고 결과를 README에 추가. (2012-04-09와 2026-10-14 예비 결과 기록 완료.)
- 2027.01–03: R1–R4 (임계값 민감도, 날짜 간 일반화, 데이터셋 간 일반화(CAIDA 승인 시), 특징 기여). 자세한 내용은 `docs/design.md` 3.2절.

## 한계

- 15분 trace라 긴 flow는 잘립니다. trace 끝 근처에서 시작한 flow는 byte_count가 실제보다 작게 나올 수 있습니다. `--tail-sec` 옵션이 있지만 기본은 끄고 두며, 영향은 날짜 간 실험에서 따로 잽니다.
- trace 시작 전에 시작된 flow는 "처음 N개" 패킷이 실제 처음이 아닐 수 있습니다.
- IPv4 TCP/UDP만 다룹니다. IPv6, fragment, 그 밖의 프로토콜은 버립니다.
- flow는 한 pcap 파일 안에서만 묶습니다. idle timeout과 FIN/RST 기준 분리는 하지 않습니다.
- CAIDA는 아직 연결하지 않았습니다. 승인 전까지 일반화는 MAWI 날짜 간으로 제한됩니다.
- 단일 수집 지점이고 하루 15분씩만 봅니다. 날짜 간 차이의 원인을 단정할 수 없습니다.
- 문헌 중 일부([1-a], [5], [6])는 본문을 확인하지 못했습니다. 자세한 내용은 `docs/problem.md` 7.2절.
