# 설계: 초반 N패킷 Elephant 예측 견고성 분석 파이프라인

기준값은 [problem.md](problem.md)를 따른다: 기본 N = 4 데이터 패킷, elephant = train 바이트 상위 1%(상위 10%는 누설 대조군, problem.md 3.2.1), 시간순 70/30 분할, 주·보조 지표. 연구 질문 RQ1–RQ3과 위험은 problem.md 8절에 있다. 이 문서는 그 값을 코드 구조, 파일 형식, 실험 계획으로 옮긴다. 문헌 번호 [1]–[9]는 problem.md 7.1절 표의 번호다. 각 결정마다 출처를 적었다. 논문 근거가 없는 결정은 "근거: 실용 판단"으로 적었다.

## 0. 결정과 출처 요약

| 결정 | 값 | 출처 | 이전 판 대비 |
| --- | --- | --- | --- |
| 프로젝트 방향 | 견고성 분석: 날짜 간·데이터셋 간 일반화(RQ1), 임계값 민감도(RQ2), 특징 기여(RQ3) | 사용자 결정. 차별점 근거는 problem.md 8.2 (본문 확인 범위 한정) | **변경** (이전: 베이스라인 + 여러 확장 실험) |
| 임계값 정의 | `bytes_pct`(train 바이트 백분위수, 기본), `bytes_fixed`(고정 바이트), `pkts_pct`(train 패킷 수 백분위수) | [9](바이트 백분위수), [3](고정 크기), [2](패킷 수 기준) | **추가** (이전: 바이트 백분위수·고정 바이트만) |
| 임계값 맞추는 곳 | 기본 train. 분석용으로 test도 허용(배포 불가 설정으로 표시) | 근거: 실용 판단. 날짜 간 임계값 이동 효과를 분리하기 위함 | **추가** |
| 학습·평가 데이터 | 같은 CSV 시간순 분할(기본) 또는 train CSV와 test CSV를 따로 지정 | [9](도메인 간 평가) | **추가** |
| 결과 기록 | 실행마다 결과 CSV에 한 행 추가(2절 ④) | 근거: 실용 판단. sweep 결과를 표로 모으기 위함 | **추가** |
| 비교 모델 집합 (2027) | RandomForest, LogisticRegression, HistGradientBoosting (모두 scikit-learn) | [9](RF·LR 등 여러 모델 비교, XGBoost·LightGBM이 RF와 비슷하다고 보고 → 같은 계열인 HGB로 대체) | **추가** |
| 조기 판정 정지 규칙 | 이번 범위 밖, 추후 구현 후보 | 7절 | **추가** (후보로만) |
| trace 끝 절단 필터 | `tail_sec`(기본 0). 0보다 크면 파일마다 max(start_ts) − tail_sec 이후에 시작한 flow 제외 | 근거: 실용 판단. 문헌과 비교 가능하도록 기본은 끔. 영향은 R2 (d)에서 측정 | **추가** |
| `pkts_pct`의 reg 보조 지표 | 같은 p로 구한 byte_count 백분위수(`reg_thr_value`)로 근사 계산 | 근거: 실용 판단. clf와 다른 라벨 정의임을 표시 | **변경** (이전: N/A) |
| 패킷 세는 기준 | 데이터 패킷(페이로드 > 0)만 센다. 제어 패킷 제외 | [1](SYN·Keep-Alive·데이터 없는 ACK 제거), [3](동기화 패킷 다음 데이터 패킷) | **변경** (이전: 모든 패킷) |
| 기본 예측 시점 | 처음 N = 4개 데이터 패킷 | [1](P = 1–10 중 NMI 최고가 P = 4), [3](3개) | **변경** (이전: N = 5) |
| N ablation | N ∈ {0, 1, 3, 4, 10} | [4](헤더만 = 0), [3](3), [1](4, 실험 범위 상한 10) | **변경** (이전: {1, 3, 5, 10}) |
| 기준선 | N = 0 헤더 전용 모델 | [4](첫 패킷 5-tuple 헤더만) | **변경** (이전: N = 1 첫 패킷 기준선) |
| 특징: 패킷 크기 | 처음 N개 데이터 패킷의 페이로드 길이 | [1](페이로드 크기), [3](처음 3개 데이터 패킷 크기) | **변경** (이전: IP total length) |
| 특징: 도착 간격 | 연속 데이터 패킷 간격 N−1개 | 근거: 실용 판단. [1]은 처음 4개 패킷에서 평균 도착 간격이 응용 구분에 도움이 안 된다고 보고. ablation으로 제거 효과를 2027에 확인 | 유지 |
| 특징: proto, 포트 | proto, src_port, dst_port | [3], [4](둘 다 헤더 5-tuple 사용) | 유지 |
| 특징 제외: IP 주소 | 베이스라인에서 안 씀 | [3], [4]는 사용. 제외 이유는 cross-dataset 일반화 [9]. IP 비트 특징은 2027 비교 | 이유 **변경** (이전: 익명화) |
| 특징 보류 | 클라이언트/서버(첫 패킷 TCP 플래그로 근사), 방향 | [3], [1] | 유지 (2027) |
| elephant 임계값 | train 바이트 99번째 백분위수(상위 1%, `bytes_pct` p = 0.01) | [9](도메인별 바이트 백분위수 방식). 상위 10%는 MAWI에서 elephant의 51.6%가 데이터 패킷 4개 미만이라 누설 구조가 되어 기본값에서 뺐다(problem.md 3.2.1, 임시 측정, 한 trace). [3]의 고정 임계값은 데이터셋마다 elephant 비율이 12%–0.1% 미만으로 달라짐 | **변경** (이전: 상위 10%) |
| train 행 수 제한 | `--train-max-rows N`(기본 전체). y 기준 층화 추출, 임계값은 전체 train으로 구함, test는 줄이지 않음 | 근거: 실용 판단. RF 학습 비용(train 180만 행, n=4 1회 41분, 최대 7GB; n_jobs 기본 1일 때) | **추가** |
| flow 해시 샘플링 | `preprocess --sample-rate r`. 5-tuple crc32로 flow를 결정적으로 고르고 고른 flow의 패킷은 전부 유지 | 근거: 실용 판단. 2026-10-18 trace(gz 6.1GB, 2.4억 패킷)는 flow dict가 약 33GB 필요할 것으로 추정(가정), RAM 15.6GB | **추가** |
| 분할 | 시작시각 순 70/30 | 근거: 실용 판단. 문헌은 무작위 80/20 [4], 층화 k-fold [8][9]. 운영 조건에 맞추려 시간순 유지 | 유지 |
| 분류 모델 | RandomForestClassifier(100 trees, class_weight="balanced") | [9](같은 설정을 cross-domain 실험에 사용), [3](elephant 오류에 비율 역수 가중치) | 출처 **추가** (이전: 논문 근거 없음) |
| 회귀 모델 | RandomForestRegressor, 대상 log10 바이트 | 근거: 실용 판단. [4]도 바이트 크기를 회귀(정규화한 라벨) | 유지 |
| 주 지표 | precision, recall, F1 (elephant 양성), log10 MAE | [2](FP/FN 절충), [3](TPR = recall) | 유지 |
| 보조 지표 | TNR, 트래픽 커버리지, flow table 감소 배수 | [3](TNR), [4](커버리지·감소 배수) | TNR **추가** |
| 회귀 → 분류 비교 | 회귀 예측에 같은 임계값을 적용해 보조 지표 계산 | [4](회귀 출력에 임계값 적용) | **추가** |
| 차별점 실험 | R1 임계값 민감도, R2 날짜 간 일반화, R3 데이터셋 간 일반화(CAIDA 승인 시), R4 특징 기여 (3.2절) | problem.md 8 | **변경** (이전: E4–E9) |
| 선택 후보 | IP 비트·클라이언트/서버 특징 [3][4], 선형층 NN [4], 커버리지–감소 곡선 [4], T ms 예측 시점 [6], 구간 분류 [5] | 각 표기 | **강등** (이전: 일정에 있는 실험 → 여유 시 후보) |

### S3·S4 확장 범위 (spec 작성 시 기준)

S3과 S4의 범위는 plan의 원래 목표 문구보다 커졌다. spec을 쓸 때는 **이 체크리스트가 plan 목표 문구보다 우선한다**. 예상 변경 경로는 그대로다: `src/flowpred/features.py`, `src/flowpred/train.py`, `tests/test_features.py`, `tests/test_train.py`. 반복 실행(sweep) 자동화, 결과 요약 표, `lr`·`hgb` 모델, 특징 묶음 제거 옵션, permutation importance는 이 범위 밖이다(2027, 6절).

**S3 — `features.py`, `tests/test_features.py`**
- 함수:
  - [ ] `drop_tail(df, tail_sec)`: tail_sec > 0이면 start_ts > (이 df의 max(start_ts) − tail_sec)인 flow를 뺀다. 0이면 그대로 돌려준다. 기준은 파일(CSV) 하나 단위다(2절 ②).
  - [ ] 시간순 분할 함수: start_ts 순 앞 70% / 뒤 30%. 라벨과 따로 둔다.
  - [ ] `fit_threshold(df, 정의, 값)`: 정의는 `bytes_pct` / `bytes_fixed` / `pkts_pct`. 임계값 하나를 돌려준다.
  - [ ] `label(df, 정의, 임계값)`: 값 ≥ 임계값이면 1.
  - [ ] 특징 행렬 함수: n 인자(기본 4, 0 ≤ n ≤ 10). 열 순서는 2절 ② 표대로이고, 열 수는 n = 0이면 3, n ≥ 1이면 2n + 3이다. 회귀 대상 y_log = log10(byte_count).
  - [ ] 특징 묶음 상수: header(proto, src_port, dst_port), size(n_seen, plen_*), timing(iat_*).
- 테스트:
  - [ ] n = 0, 1, 4에서 특징 열 수·순서
  - [ ] 세 임계값 정의 각각의 경계 라벨(값 = 임계값이면 1)
  - [ ] `drop_tail`: 경계 바로 안쪽 flow는 남고 tail 구간 flow는 빠짐. tail_sec = 0이면 행 수가 그대로
  - [ ] n_seen = `plen_1…plen_n` 중 0이 아닌 개수

**S4 — `train.py`, `tests/test_train.py`**
- CLI 인자:
  - [ ] train CSV, 선택적인 test CSV(없으면 시간순 분할)
  - [ ] n(기본 4)
  - [ ] 임계값 정의(기본 `bytes_pct`)와 값(기본 0.01)
  - [ ] `--train-max-rows`(기본 전체)
  - [ ] 임계값 기준 구간 `train` / `test`(기본 train)
  - [ ] tail_sec(기본 0)
  - [ ] 모델(지금은 `rf`만)
  - [ ] 결과 CSV 경로(선택)
- 처리:
  - [ ] 파일마다 `drop_tail` → (test CSV가 없으면) 분할 → 기준 구간에서 임계값 구하기 → 라벨 → 학습·평가
  - [ ] 분류기 RandomForestClassifier(100, balanced, random_state=0)와 회귀기 RandomForestRegressor(100, random_state=0)
  - [ ] reg 보조 지표의 바이트 임계값 `reg_thr_value`: `bytes_pct`·`bytes_fixed`에서는 thr_value와 같다. `pkts_pct`에서는 같은 p와 같은 기준 구간으로 구한 byte_count 백분위수다(2절 ④).
- 출력:
  - [ ] 표준 출력: 2절 ④ 예시 형식
  - [ ] 결과 CSV: 2절 ④의 26열을 그 순서로 한 행 덧붙인다. 파일이 없으면 헤더부터 쓴다. N/A는 빈 값으로 쓴다. 열이 바뀌었으므로 이전 열 수로 쓴 기존 파일에 이어 쓰지 않고 새 파일에 쓴다.
- 테스트 (합성 flow 표로 끝까지 실행):
  - [ ] precision/recall/F1/TNR ∈ [0, 1]
  - [ ] MAE는 0 이상의 유한값
  - [ ] coverage ∈ [0, 1], reduction ≥ 1 또는 N/A
  - [ ] 결과 CSV에 26열 헤더와 행 하나가 생기고, 두 번 실행하면 행이 둘이 됨
  - [ ] test CSV를 따로 준 실행이 동작함
  - [ ] `pkts_pct`에서 reg_thr_value가 채워지고 reg 지표가 계산됨

### 바뀐 결정이 다음 하위 작업에 주는 영향

- **S2 (전처리)**
  - 패킷마다 페이로드 길이를 헤더 필드로 계산한다. TCP는 `ip.len − 4·ip.hl − 4·tcp.off`, UDP는 `ip.len − 4·ip.hl − 8`이다.
  - 페이로드 > 0인 패킷만 처음 10개까지 `plen_k`, `iat_k`로 저장한다.
  - `pkt_count`, `byte_count`는 제어 패킷을 포함한 전체 패킷 기준으로 그대로 센다.
  - 테스트의 합성 pcap에 페이로드 없는 SYN/ACK를 넣는다. 그 패킷이 `plen_*`에는 안 들어가고 `pkt_count`, `byte_count`에는 들어가는지 확인한다.
  - CSV 열 이름이 `len_k`에서 `plen_k`로 바뀐다.
- **S3 (라벨·특징)**: 위 "S3·S4 확장 범위" 체크리스트를 따른다. 이 체크리스트를 만든 이유는 다음과 같다.
  - 데이터 패킷 기준으로 바뀌어 n = 0을 허용하고, n_seen을 0이 아닌 plen 개수로 센다.
  - 다른 날짜 CSV에 train 임계값을 적용하려면 임계값을 구하는 함수와 적용하는 함수가 따로 있어야 한다.
  - R4는 특징 묶음 상수가 필요하다.
  - trace 끝 절단을 따로 보려면 분할 앞에 `drop_tail`이 있어야 한다.
- **S4 (학습·평가)**: 위 체크리스트를 따른다. 이 체크리스트를 만든 이유는 다음과 같다.
  - TNR과 reg 보조 지표가 추가됐다.
  - R1–R3에는 임계값 정의·기준 구간·test CSV·tail_sec 인자가 필요하다.
  - sweep 결과를 모으려면 결과 CSV 누적이 필요하다.
  - `pkts_pct`의 reg 지표 N/A 문제를 `reg_thr_value`로 해결했다.
- **범위 경계**: 여러 설정을 반복 실행하는 sweep 자동화와 결과 요약 표 생성은 S2–S4 범위가 아니다. 2027.01–03 작업이다(6절). S2–S4는 단일 실행 하나가 위 인자를 받고 결과 한 행을 남기는 데까지 만든다.
- **S5 (README)**: 위 기본값과 인자를 반영한다.

## 1. 파이프라인 개요

```
pcap(.pcap / .pcap.gz)
   │  ① 전처리  src/flowpred/preprocess.py  (dpkt)
   ▼
flow 표 CSV  (data/processed/flows.csv, 처음 10개 데이터 패킷까지 저장)
   │  ② 라벨·특징  src/flowpred/features.py  (n 인자로 앞 n개만 사용)
   ▼
특징 행렬 X, 라벨 y, 회귀 대상 y_log  (메모리 안의 pandas DataFrame)
   │  ③ 모델  src/flowpred/train.py  (scikit-learn)
   ▼
학습된 분류기·회귀기  (메모리 안)
   │  ④ 평가  src/flowpred/train.py
   ▼
지표 출력 (표준 출력: 주 지표 + 보조 지표)
```

- 파일로 남기는 중간 산출물은 flow 표 CSV 하나다. pcap 파싱이 가장 느리므로 그 결과만 저장한다. 라벨·특징·학습·평가는 CSV에서 매번 다시 계산한다.
- 전처리는 처음 **10개**(ablation 최대값) 데이터 패킷까지 저장한다. 특징 단계는 그중 앞 n개(기본 4)만 쓴다. 그래서 ablation {0, 1, 3, 4, 10}을 CSV 하나로 돌릴 수 있다.
- 모델 파일은 저장하지 않는다.

## 2. 단계별 입출력

### ① 전처리 (pcap → flow 표)

- 입력: libpcap 파일 1개. `.gz`이면 gzip으로 풀면서 읽는다. 링크 타입은 Ethernet(MAWI)이다. raw IP(CAIDA)는 추후 분기를 추가한다.
- 처리:
  1. 패킷마다 IPv4 + TCP/UDP인지 확인한다. 아니면 버린다. fragment offset ≠ 0인 패킷도 버린다.
  2. 키 (src_ip, dst_ip, src_port, dst_port, proto)로 flow를 모은다.
  3. flow마다 다음을 기록한다.
     - 시작시각(첫 패킷 timestamp, 제어 패킷 포함)
     - 패킷 수와 바이트 수(IP total length 합). 둘 다 모든 패킷 기준이다.
     - 페이로드 길이 > 0인 패킷 가운데 처음 N_max = 10개의 페이로드 길이와 도착 간격
     - 페이로드 길이는 헤더 필드로 계산한다(0절 S2 식). MAWI는 페이로드를 잘라 저장하므로 캡처 길이를 쓰지 않는다.
  4. 시작시각 오름차순으로 정렬해 CSV로 쓴다.
- 선택 인자: 읽을 최대 패킷 수(큰 MAWI 파일 앞부분만 쓰기 위함), N_max(기본 10), `--sample-rate r`(0 < r ≤ 1, 기본 1.0).
- flow 해시 샘플링 (`--sample-rate r`, r < 1):
  - 방향 5-tuple의 crc32 해시로 flow를 결정적으로 고른다. 같은 입력이면 항상 같은 flow가 뽑힌다. 고른 flow의 패킷은 전부 유지한다.
  - CLI는 `<출력 CSV>.meta.json`에 `{"sample_rate": r}`을 쓴다. train은 이 파일을 읽어 결과 CSV의 `sample_rate` 열에 기록한다. 파일이 없으면 1.0이다. train CSV와 test CSV의 sample_rate가 다르면 오류다.
  - 근거: 2026-10-18 trace는 gz 6.1GB, 2.4억 패킷이다. 샘플링 없이는 flow dict가 약 33GB 필요할 것으로 추정한다(가정; 2012 trace 측정은 flow 258만 개에서 최대 4.8GB, 10.5분). RAM은 15.6GB다.
  - 패킷은 전부 읽으므로 시간은 거의 줄지 않고 메모리가 준다.
  - 비율 지표(precision, recall, F1)는 영향이 없다고 본다. table_reduction 같은 절대 규모 지표는 sample_rate로 나눠 해석한다.
- 출력: CSV, 헤더 포함, flow 1개가 1행.

| 열 | 형식 | 설명 |
| --- | --- | --- |
| src_ip | 문자열 | 점 표기 IPv4 |
| dst_ip | 문자열 | 점 표기 IPv4 |
| src_port | 정수 | 0–65535 |
| dst_port | 정수 | 0–65535 |
| proto | 정수 | 6(TCP) 또는 17(UDP) |
| start_ts | 실수 | 첫 패킷 시각, Unix epoch 초 |
| pkt_count | 정수 | flow 전체 패킷 수 (제어 패킷 포함, ≥1) |
| byte_count | 정수 | flow 전체 바이트 수, IP total length 합 |
| plen_1 … plen_10 | 정수 | k번째 데이터 패킷의 페이로드 길이(바이트). 데이터 패킷이 k개 미만이면 0 |
| iat_1 … iat_9 | 실수 | k번째와 k+1번째 데이터 패킷 사이 간격(초). 해당 패킷이 없으면 0 |

열 순서는 위 표 그대로다(N_max = 10이면 8 + 10 + 9 = 27열).

### ② 라벨·특징 (flow 표 → X, y, y_log)

- 입력: ①의 CSV를 읽은 DataFrame과 예측 시점 n(기본 4, 0 ≤ n ≤ N_max).
- trace 끝 절단 필터 `tail_sec` (기본 0 = 사용 안 함):
  - 15분 trace의 끝 근처에서 시작한 flow는 trace가 끝나며 잘린다. 그래서 byte_count와 pkt_count가 실제보다 작게 나오고 mice로 잘못 라벨될 수 있다.
  - tail_sec > 0이면 분할 **전에** start_ts > (max(start_ts) − tail_sec)인 flow를 뺀다.
  - 기준은 **파일 단위**다. max(start_ts)는 그 CSV(= trace 하나)에서 계산한다.
    - train CSV와 test CSV를 따로 주면 각 파일에서 따로 계산해 둘 다에 적용한다.
    - 시간순 분할이면 CSV 하나에 적용한 뒤 분할한다.
  - max(start_ts)는 trace 끝 시각의 근사다.
  - 기본값을 0으로 두는 이유: 이 필터는 문헌([1][2][3][4])에 없는 전처리다. 기본 베이스라인(E1–E3)은 문헌 방식과 비교할 수 있게 그대로 둔다. 절단 영향은 R2 (d)에서 따로 잰다.
  - trace 시작 전에 시작된 flow(좌측 절단)는 이 옵션으로 다루지 않는다(problem.md 3.1 한계).
- 분할: test CSV를 따로 주지 않으면 start_ts 순으로 앞 70%를 train, 뒤 30%를 test로 나눈다. test CSV를 따로 주면 train CSV 전체가 train이고 test CSV 전체가 test다(날짜 간·데이터셋 간 평가). 분할을 라벨보다 먼저 한다.
- 라벨 (임계값 정의):

| 정의 | 값 | 임계값 | 라벨 = 1 조건 |
| --- | --- | --- | --- |
| `bytes_pct` (기본) | 상위 비율 p (기본 0.01) | 기준 구간 byte_count의 (1 − p) 백분위수 | byte_count ≥ 임계값 |
| `bytes_fixed` | 바이트 값 | 그 값 그대로 | byte_count ≥ 임계값 |
| `pkts_pct` | 상위 비율 p | 기준 구간 pkt_count의 (1 − p) 백분위수 | pkt_count ≥ 임계값 |

  - 기준 구간은 기본이 train이다. 분석용 옵션으로 test를 기준 구간으로 쓸 수 있다. 이 옵션은 test 정보를 쓰므로 배포 가능한 성능이 아니며, 결과 CSV의 `thr_fit` 열에 표시한다.
  - train에서 구한 임계값을 test에 그대로 적용한다.
- 회귀 대상: `y_log = log10(byte_count)`. byte_count ≥ 20이므로 log 문제가 없다.
- 특징 행렬 X: 아래 순서로 고정한다. 열 수는 n = 0이면 3, n ≥ 1이면 2n + 3이다. pkt_count와 byte_count는 정답 누설이라 넣지 않는다.

| 순서 | 열 | 설명 | 출처 |
| --- | --- | --- | --- |
| 1 | proto | 6 / 17 | [3][4] |
| 2 | src_port | | [3][4] |
| 3 | dst_port | | [3][4] |
| 4 | n_seen | `plen_1…plen_n` 중 0이 아닌 개수 (n ≥ 1일 때만) | 실용 판단 |
| 5 … 4+n | plen_1 … plen_n | n ≥ 1일 때만 | [1][3] |
| 5+n … 3+2n | iat_1 … iat_(n−1) | n ≥ 2일 때만 | 실용 판단 |

- 출력: train/test 각각 X(DataFrame), y(0/1 Series), y_log(실수 Series)와 사용한 임계값(바이트).

### ③ 모델

- 분류: `RandomForestClassifier(n_estimators=100, class_weight="balanced", random_state=0)`.
  - [9]가 cross-domain 실험에서 쓴 것과 같은 트리 수와 class_weight 설정이다.
  - [3]도 elephant 오류에 클래스 비율 역수 가중치를 줘서 불균형을 보정했다.
  - [9]는 RobustScaler를 함께 썼지만, 트리 모델은 스케일에 영향을 받지 않아 생략한다.
- 회귀: `RandomForestRegressor(n_estimators=100, random_state=0)`, 대상은 y_log.
- 두 RF 모두 `n_jobs=-1`로 학습한다. 측정치(train 180만 행, n = 4 1회 41분, 최대 7GB)는 n_jobs 기본값 1일 때의 값이다.
- `--train-max-rows N`: 필터(tail) 뒤 train이 N행보다 많으면 y 라벨 기준 층화 추출(random_state=0)한 N행으로 모델을 학습한다. 임계값, 라벨, `train_flows`는 전체 train 기준이고 test는 줄이지 않는다. 한 클래스의 양성이 층화하기에 부족하면 ValueError가 난다(비층화로 대체하지 않음).
- 논문별 모델 참고:
  - 다른 문헌의 모델: clustering [1], 베이즈 임계값 [2], online NN·GP·oBMM [3], 선형층 NN [4], DNN/CNN/LSTM/AE [8]
  - [4]식 간단한 NN은 선택 후보로 둔다.
- 비교 모델 집합 (R1, 2027): 아래 셋 모두 `class_weight="balanced"`이고 모두 scikit-learn이라 새 의존성이 없다. RQ2의 "최적 모델"은 이 집합 안에서의 비교다.
  - `rf`: 위 RandomForest
  - `lr`: StandardScaler + LogisticRegression ([9]가 비교한 모델 중 하나)
  - `hgb`: HistGradientBoostingClassifier ([9]가 RF와 비슷하다고 보고한 XGBoost·LightGBM 계열)
- 입력: train의 X, y / X, y_log. 출력: 학습된 모델 객체(메모리).

### ④ 평가

- 입력: test의 X, y, y_log, byte_count와 ③의 모델.
- 주 지표:
  - `precision_score`, `recall_score`, `f1_score`(pos_label=1, zero_division=0)
  - `mean_absolute_error`(y_log 기준)
- 보조 지표:
  - `tnr = recall_score(y, ŷ, pos_label=0, zero_division=0)` [3]
  - `coverage = sum(byte_count[ŷ=1]) / sum(byte_count)` [4]
  - `table_reduction = len(test) / count(ŷ=1)` [4]. count(ŷ=1) = 0이면 `N/A`
  - 위 coverage, table_reduction을 두 가지 예측으로 각각 계산한다.
    - ŷ = 분류기 예측
    - ŷ_reg = (회귀 예측 y_log ≥ log10(reg_thr_value)) [4]
  - `reg_thr_value`(reg 지표에 쓰는 바이트 임계값):
    - `bytes_pct`·`bytes_fixed`: thr_value와 같다.
    - `pkts_pct`: 분류 임계값이 패킷 수라 회귀 예측(바이트)과 바로 비교할 수 없다. 그래서 같은 p와 같은 기준 구간(thr_fit)으로 구한 byte_count의 (1 − p) 백분위수를 대신 쓴다.
    - 이 경우 reg 지표는 분류 라벨(패킷 수 기준 상위 p)과 **정의가 다른 근사**다(바이트 기준 상위 p를 고른 것). 그래서 `pkts_pct` 행에서는 clf 지표와 reg 지표를 같은 라벨에 대한 비교로 읽으면 안 된다(3.2 R1 참고).
- 함께 출력: train/test flow 수, test 양성 수, 임계값, reg_thr_value, n, tail_sec, test에서 n_seen < n인 flow 비율(short_flows).
- 출력 예:

```
sample_rate=1.0 n=4 flows train=70000 test=30000 threshold_bytes=12345 reg_thr_value=12345 test_elephants=295 short_flows=0.55 tail_sec=0.0 train_max_rows=all
precision=0.71 recall=0.64 f1=0.67 tnr=0.97
clf coverage=0.82 table_reduction=9.8
reg coverage=0.79 table_reduction=11.2
mae_log10=0.42
```

(숫자는 형식 예시이며 실제 결과가 아니다.)

- 결과 CSV (경로를 줄 때만, 실행마다 한 행 추가). 아래 순서로 총 26열이다(`train.py`의 COLUMNS와 같다). 열이 바뀌었으므로 이전 열 수의 기존 파일에 이어 쓰지 말고 새 파일을 쓴다.
  - 설정 (13): `train_csv, test_csv, n, model, features, thr_def, thr_param, thr_fit, thr_value, reg_thr_value, tail_sec, train_max_rows, sample_rate`
  - 규모 (4): `train_flows, test_flows, test_pos, short_flows`. flow 수는 tail_sec 필터 뒤의 수다.
  - 지표 (9): `precision, recall, f1, tnr, mae_log10, clf_coverage, clf_reduction, reg_coverage, reg_reduction`
  - `train_max_rows`는 제한을 안 줬으면 빈 값이고, `sample_rate`는 `.meta.json`이 없으면 1.0이다. table_reduction 같은 절대 규모 지표는 `sample_rate`로 나눠 해석한다.
  - `test_csv`는 시간순 분할이면 빈 값이다. `features`는 지금은 `all`만 쓴다(R4에서 묶음 제거 시 `-timing` 같은 값). N/A는 빈 값으로 쓴다.

### 실행 형태

프로젝트 루트에서 모듈로 실행한다. 아래는 구현된 실제 CLI다(README와 같다).

```
python -m flowpred.preprocess <pcap 경로> <출력 CSV 경로> [최대 패킷 수] [--sample-rate r]
python -m flowpred.train TRAIN_CSV [--test TEST_CSV] [--n 4]
    [--thr-def bytes_pct|bytes_fixed|pkts_pct] [--thr-param 0.01]
    [--thr-fit train|test] [--tail-sec 0] [--train-max-rows N]
    [--model rf] [--out RESULTS_CSV]
```

- 위치 인자는 `TRAIN_CSV` 하나다. `--thr-param`은 `*_pct`에서 상위 비율 p, `bytes_fixed`에서 바이트 값이다.
- `--sample-rate`를 주면 전처리가 `<출력 CSV>.meta.json`도 쓴다(2절 ①).
- `src/`는 패키지로 설치하지 않으므로 모듈 실행 시 `PYTHONPATH=src`가 필요하다. pytest는 각 테스트 파일이 `src`를 `sys.path`에 직접 넣는다.

## 3. 실험 계획

모든 실험은 같은 train 스크립트를 인자만 바꿔 실행하고 결과 CSV에 행을 쌓는다. 결과 표는 이 CSV를 pandas로 묶어 만든다.

### 3.1 기본 베이스라인 묶음 (2026.12, 최소 베이스라인 완료 조건)

공통 설정: MAWI trace 1개, 시간순 70/30, `bytes_pct` 0.01(상위 1%), 임계값 기준 구간 train, tail_sec = 0, `rf`.

| 실험 | 내용 | 출처 | 결과 표 |
| --- | --- | --- | --- |
| E1 기본 베이스라인 | n = 4 | [1] | 지표 한 행 |
| E2 헤더 전용 기준선 | n = 0 (proto·포트만) | [4] | E1과 나란히 |
| E3 N ablation | n ∈ {0, 1, 3, 4, 10} | [1][3][4] | 행 = n, 열 = precision/recall/F1/TNR/coverage/reduction/short_flows |

E1–E3은 S2–S4 산출물만으로 실행한다(5회 실행).

### 3.2 차별점 묶음 (2027.01–03)

| 실험 | RQ | 입력 | 바꾸는 것 | 고정하는 것 | 주 지표 | 결과 표 형태 |
| --- | --- | --- | --- | --- | --- | --- |
| R1 임계값 민감도 | RQ2 | MAWI trace CSV 1개(시간순 분할). 같은 경향 확인을 위해 R2의 날짜 2–3개에서 반복 | 임계값 정의·값: **최소 비교 세트**는 `bytes_pct` p ∈ {0.10(누설 대조군), 0.01(기본), 0.001}과 `bytes_fixed` ∈ {100 KB}이다. 핵심은 "상위 10%·1%·0.1%와 고정 100 KB 비교"다. 여유가 있으면 `bytes_fixed` ∈ {10 KB, 1 MB, 10 MB}, `pkts_pct` p ∈ {0.01, 0.05, 0.10, 0.20}를 더한다. 기준 구간 ∈ {train, test}(백분위수 정의만). n ∈ {0, 1, 3, 4, 10}. 모델 ∈ {rf, lr, hgb} | 데이터, tail_sec = 0 | F1, coverage, reduction, test_pos | 상위 10% 행은 누설 대조군으로 표시하고 elephant 종류별 short_flows 비율(problem.md 3.2.1)을 함께 적는다. (a) 임계값 설정마다 F1 최고인 n·모델과 그 값, test_pos. (b) `bytes_pct`·rf에서 행 = n, 열 = p인 F1 표. (c) 같은 설정의 train 기준 − test 기준 F1 차이. (d) clf와 reg의 coverage/reduction 비교. 단 `pkts_pct` 행의 reg 값은 바이트 기준 근사(reg_thr_value)라 clf와 같은 라벨 비교가 아님을 표에 표시 |
| R2 날짜 간 일반화 | RQ1 | MAWI 날짜 K개(K ≥ 5: 같은 달 날짜 여러 개 + 약 1개월 뒤 + 약 1년 뒤)의 CSV | train 날짜 i × test 날짜 j. n ∈ {0, 4, 10}. 기준 구간 ∈ {train, test}. (d)에서만 tail_sec ∈ {0, 60, 120} | `bytes_pct` 0.01, `rf`, tail_sec = 0((d) 제외) | F1, coverage | (a) K×K F1 표: 대각선은 같은 날짜 안 시간순 분할, 나머지는 i로 학습·j로 평가. (b) 하락 표: test 날짜 j마다 "같은 날짜 F1 − 다른 날짜에서 학습한 F1"의 최소·중앙·최대. (c) 기준 구간 train vs test 비교로 임계값 이동분 분리. (d) 절단 영향: n = 4에서 tail_sec ∈ {0, 60, 120}마다 (b)를 다시 계산한 표(행 = tail_sec, 열 = 하락의 최소·중앙·최대, 빠진 flow 비율). tail_sec을 키울 때 하락이 줄어드는 만큼을 trace 끝 절단의 영향으로 본다 |
| R3 데이터셋 간 일반화 | RQ1 | MAWI CSV와 CAIDA CSV (CAIDA 승인 시에만) | MAWI → CAIDA, CAIDA → MAWI. n ∈ {0, 4, 10} | R2와 같음 | F1, coverage | R2 (a)(b)와 같은 형태 |
| R4 특징 기여 | RQ3 | R2의 날짜 CSV | 특징 묶음 제거(header / size / timing을 하나씩 뺌). 같은 날짜 test와 다른 날짜 test 각각에서 permutation importance(scikit-learn `permutation_importance`, scoring = F1) | n = 4, `bytes_pct` 0.01, `rf` | ΔF1 | 행 = 특징 묶음, 열 = 같은 날짜 ΔF1, 다른 날짜 ΔF1(중앙값) |

- R1의 기준 구간 test 설정과 R2·R3의 기준 구간 test 설정은 분석용이다. 성능 수치로 보고하지 않고, train 기준 결과와의 차이(임계값 이동 효과)로만 쓴다.
- R1의 `bytes_fixed` 값은 [3]이 쓴 범위(10 Kb–1 Mb, 본문 표기)를 참고했다. 최소 세트의 100 KB는 [3]의 라우팅 실험 값이다. 백본 링크라 선택 값은 10 MB까지 넓혀 바이트 단위로 정했다.
- R1에서 sample_rate가 다른 CSV를 섞지 않는다. table_reduction은 sample_rate로 나눠 해석한다(2절 ①).
- `pkts_pct`는 [2]의 패킷 수 기준 정의를 백분위수 형태로 옮긴 것이다. [2]의 원래 정의(전체 패킷의 0.1%)는 양성이 너무 적어 쓰지 않는다(problem.md 3.2).
- 결과 표에는 항상 test_pos를 함께 적는다(problem.md 8.4).

### 3.3 S2–S4에 필요한 것 (요약)

| 실험 | 필요한 CSV | 필요한 CLI 인자 | 하위 작업 |
| --- | --- | --- | --- |
| E1–E3 | flow 표 CSV 1개 | n | S2, S3, S4 |
| R1 | flow 표 CSV 1개 | n, 임계값 정의·값, 기준 구간, 모델(`lr`, `hgb`는 2027 추가), 결과 CSV | S3, S4 (인터페이스), 2027 (모델 추가·sweep) |
| R2, R3 | 날짜·데이터셋마다 flow 표 CSV 1개 | train CSV와 test CSV 따로, tail_sec, 결과 CSV | S3 (`drop_tail`), S4 (인터페이스), 2027 (데이터 수집·sweep) |
| R4 | R2와 같음 | 특징 묶음 제거 옵션 | S3 (묶음 상수), 2027 (옵션·permutation importance) |

### 3.4 선택 후보 (여유가 있을 때만)

일정에 넣지 않는다. 차별점 묶음이 끝난 뒤 시간이 남으면 고른다.
- IP 주소 비트, 클라이언트/서버(첫 패킷 TCP 플래그) 특징 [3][4]
- 양방향 결합·방향 특징 [1], TCP SYN 기준 flow 필터 [1]
- [4]식 선형층 NN, 회귀 예측 임계값을 훑은 커버리지–감소 곡선 [4]
- 처음 T ms 예측 시점 [6] (본문 미확인), coarse-grain 구간 분류 [5] (본문 미확인)
- online 학습 [3], 딥러닝 [6][8]

## 4. 디렉터리 구조

```
network_pj/
├── docs/
│   ├── problem.md          문제정의 (기준값, 관련 연구)
│   └── design.md           이 문서
├── src/
│   └── flowpred/
│       ├── __init__.py
│       ├── preprocess.py   ① pcap → flow 표 CSV (데이터 패킷 기준)
│       ├── features.py     ② 시간순 분할, 라벨, 특징 행렬(n 인자)
│       └── train.py        ③ 학습 + ④ 평가, 주·보조 지표 출력
├── tests/
│   ├── test_preprocess.py  합성 pcap → flow 수, 바이트 합, 제어 패킷 제외 확인
│   ├── test_features.py    임계값 경계 라벨, 특징 열 수(n=0:3, n≥1:2n+3)·순서 확인
│   └── test_train.py       합성 flow 표로 끝까지 실행, 지표 범위 확인
├── data/                   .gitignore로 저장소에서 제외
│   ├── raw/                내려받은 pcap(.gz)
│   └── processed/          flow 표 CSV
├── results/                결과 CSV (실행마다 한 행 누적, 집계 결과라 저장소에 둘 수 있음)
├── requirements.txt        dpkt, pandas, scikit-learn, pytest
├── .gitignore              data/, .venv/
└── README.md
```

- 환경: Python 3.11 이상, venv(`.venv/`).
- 테스트는 실제 MAWI 파일 없이 돌아야 한다. 합성 pcap은 dpkt로 테스트 안에서 만들고, 합성 flow 표는 pandas로 만든다.

## 5. CAIDA 연결 지점

CAIDA는 ①의 입력만 다르다. pcap 링크 타입이 raw IP이면 Ethernet 헤더 없이 IP부터 파싱하는 분기를 ①에 추가하고, 출력 CSV 형식(2절 표)은 그대로 둔다. ②–④는 고치지 않는다. 임계값을 비율(상위 1%)로 정하므로 데이터셋별 양성 비율이 같아 R3 비교가 가능하다 [9]. 승인이 나지 않으면 R3은 하지 않고 R2로 대신한다(problem.md 8.4).

## 6. 일정

| 기간 | 작업 | 산출물 |
| --- | --- | --- |
| 2026.09 | 주제 선정, 관련 연구 조사, MAWI 데이터 형식 확인 | 조사 메모 |
| 2026.10 | 문제정의·설계 확정(관련 연구 본문 반영), 프로젝트 골격, 전처리 구현과 테스트 | docs/problem.md, docs/design.md, preprocess.py |
| 2026.11 | S3·S4 확장 범위 체크리스트(0절) 구현: 라벨·특징(임계값 정의 3종, tail_sec 필터, 특징 묶음 상수), 단일 학습·평가 스크립트(train/test CSV 인자, 결과 CSV 한 행 기록) | features.py, train.py, 테스트 |
| 2026.12 | MAWI trace 1개로 E1–E3 결과 산출, README 정리 (최소 베이스라인 완료) | README.md, results/ 결과 CSV |
| 2027.01 | 여러 날짜 MAWI trace 수집·전처리. sweep 자동화(설정 목록을 반복 실행해 결과 CSV에 누적)와 결과 요약 표 생성 구현. 모델 `lr`·`hgb` 추가. R1 시작 | sweep 스크립트, 날짜별 flow 표 |
| 2027.02 | R1 마무리, R2 날짜 간 일반화, R4 특징 기여(묶음 제거 옵션, permutation importance) | R1·R2·R4 결과 표 |
| 2027.03 | CAIDA 승인 시 R3, 미승인이면 R2 날짜 추가. 미확인 문헌([1-a], [5], [6]) 본문 확인. 최종 정리 | 최종 보고·README 갱신 |

- 2026.09–12는 설계와 최소 베이스라인 기간이다. 단일 실행 인터페이스까지만 만든다.
- 2027.01–03은 본구현·고도화 기간이다. sweep 자동화와 차별점 실험을 한다.
- 선택 후보(3.4절)와 추후 구현 후보(7절)는 이 일정에 넣지 않는다.

## 7. 추후 구현 후보 (이번 범위 밖)

이 절은 약속이 아니다. 프로젝트 종료 후 추가할지를 사용자가 판단할 후보를 적어 둔 것이다.

**조기 판정 정지 규칙**
- 개념: N을 미리 고정하지 않고, 데이터 패킷이 하나 올 때마다 "지금 판정할지, 다음 패킷을 기다릴지"를 정하는 순차 판정이다.
- 선행연구와의 관계: 본문을 확인한 [1], [3], [4]는 모두 고정된 패킷 수(P = 4, 3개 데이터 패킷, 첫 패킷 헤더)로 판정한다. [6](본문 미확인)도 고정된 시간 창(요약상 400 ms)을 쓴다. 이 후보는 그 고정값을 flow마다 달리하는 쪽이다. 이 프로젝트의 E3 N ablation과 R1의 n별 결과는 "기다릴수록 얼마나 나아지는가"를 보여 주므로 후보를 검토할 때 근거 자료가 된다.
- 이미 열려 있는 최소 인터페이스 (추가 구현 없음):
  - 특징 함수가 n을 인자로 받는다(2절 ②).
  - flow 표가 처음 10개 데이터 패킷의 크기·간격을 저장한다(2절 ①). 그래서 같은 flow를 n = 0, 1, 2, …로 잘라 오프라인에서 순차 판정을 흉내 낼 수 있다.
  - 결과 CSV의 short_flows 열이 n을 채우기 전에 끝나는 flow 비율을 보여 준다.
- 이번 설계에는 이 후보를 위한 구현 항목을 넣지 않는다.
