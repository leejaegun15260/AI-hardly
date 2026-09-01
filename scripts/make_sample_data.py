# -*- coding: utf-8 -*-
"""
샘플 데이터 생성기 (시제품용)

실제 공공데이터가 준비되기 전까지 화면을 시험해 볼 수 있도록
data/build/*.json 을 만들어 둡니다.

나중에 할 일:
  이 파일을 scripts/collect.py 로 대체하세요.
  - 병무청 오픈API 호출 → 같은 형식의 JSON 저장
  - 커트라인 CSV 읽기(encoding='cp949') → cutoff.json 저장
  화면(web/) 은 파일 형식만 같으면 그대로 동작합니다.
"""
import json, random, pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "build"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20260901)  # 매번 같은 샘플이 나오도록 고정

BRANCH, FIELD = "육군", "기술행정병"

# (코드, 특기명, 임무, 신체등급, 면접, 흥미유형, 커트라인 기준선, 특이사항)
SPECS = [
    ("A01","전기설비 운용/정비","부대 전기설비를 점검·정비하고 발전기와 배전 계통을 운용합니다.","1~3급","실시",["R","C"],78,None),
    ("A02","일반차량 운전","병력·물자 수송 차량을 운전하고 일일 점검과 정비 지원을 합니다.","1~3급","실시",["R"],75,"운전 관련 특기는 운전면허 별도 배점체계가 적용됩니다. 실제 배점은 모집공고를 확인하세요."),
    ("A03","정보체계 운용","부대 전산망과 정보체계를 운용하고 장애 대응·보안 점검을 수행합니다.","1~3급","실시",["I","C"],83,None),
    ("A04","조리","급식 계획에 따라 조리·배식하고 조리기구와 위생을 관리합니다.","1~3급","실시",["R","S"],72,None),
    ("A05","일반의무","의무대에서 환자 접수·처치 보조와 의무물자 관리를 담당합니다.","1~3급","실시",["S","I"],80,None),
    ("A06","지원보급","보급품 청구·수령·불출과 재물 조사를 담당합니다.","1~3급","실시",["C"],74,None),
    ("A07","탄약관리","탄약고 저장 관리와 불출·회수, 안전 점검을 담당합니다.","1~3급","실시",["C","R"],73,None),
    ("A08","차량정비","전술차량의 정기·수시 정비와 부속 관리 업무를 수행합니다.","1~3급","실시",["R"],76,None),
    ("A09","통신선로 운용","유·무선 통신선로를 설치·복구하고 통신장비를 운용합니다.","1~3급","실시",["R","I"],77,None),
    ("A10","건설기계 운용","굴착기·지게차 등 건설기계를 운용해 진지공사와 물자 취급을 지원합니다.","1~3급","실시",["R"],71,None),
]

# 특기별 인정 자격/면허  (등급은 rules 파일의 배점표 키와 반드시 일치시킬 것)
CERTS = {
 "A01":[("전기기사","기사"),("전기공사기사","기사"),("전기산업기사","산업기사"),
        ("전기공사산업기사","산업기사"),("전기기능사","기능사"),("승강기기능사","기능사")],
 "A02":[("대형면허","대형·특수"),("특수면허","대형·특수"),("1종보통(수동)","1종보통(수동)"),
        ("1종보통(자동)","1종보통(자동)"),("2종보통","2종보통")],
 "A03":[("정보처리기사","기사"),("정보보안기사","기사"),("정보처리산업기사","산업기사"),
        ("네트워크관리사 2급","공인 일반자격"),("정보처리기능사","기능사"),("리눅스마스터 2급","공인 일반자격")],
 "A04":[("조리산업기사","산업기사"),("한식조리기능사","기능사"),("양식조리기능사","기능사"),
        ("중식조리기능사","기능사"),("제과기능사","기능사"),("제빵기능사","기능사")],
 "A05":[("응급구조사 1급","공인 일반자격"),("응급구조사 2급","공인 일반자격"),
        ("간호조무사","공인 일반자격"),("임상병리사","공인 일반자격"),("위생사","공인 일반자격")],
 "A06":[("물류관리사","공인 일반자격"),("유통관리사 2급","공인 일반자격"),
        ("지게차운전기능사","기능사"),("전산회계 2급","비공인 일반자격")],
 "A07":[("화약류관리기사","기사"),("화약류관리산업기사","산업기사"),("위험물산업기사","산업기사"),
        ("위험물기능사","기능사"),("산업안전산업기사","산업기사")],
 "A08":[("자동차정비기사","기사"),("자동차정비산업기사","산업기사"),("자동차정비기능사","기능사"),
        ("건설기계정비기능사","기능사")],
 "A09":[("정보통신기사","기사"),("정보통신산업기사","산업기사"),("통신선로산업기사","산업기사"),
        ("전자기능사","기능사"),("통신기기기능사","기능사")],
 "A10":[("굴착기운전기능사","기능사"),("지게차운전기능사","기능사"),("기중기운전기능사","기능사"),
        ("로더운전기능사","기능사"),("건설기계정비산업기사","산업기사")],
}

# 특기별 인정 전공(학과)
MAJORS = {
 "A01":["전기과","전기공학과","전기전자공학과","전기제어과"],
 "A02":["자동차과","기계과","운송과"],
 "A03":["컴퓨터공학과","소프트웨어학과","정보통신과","정보보호학과"],
 "A04":["조리과","외식조리과","식품영양학과","호텔조리과"],
 "A05":["간호학과","응급구조학과","보건행정과","임상병리학과"],
 "A06":["물류학과","경영학과","유통경영과","회계학과"],
 "A07":["화학공학과","산업안전과","소방안전과"],
 "A08":["자동차과","기계공학과","기계설비과"],
 "A09":["정보통신과","전자공학과","통신공학과"],
 "A10":["건설기계과","토목과","건축과"],
}

ROUNDS = [5, 8, 11]      # 회차 (월)
YEARS  = [2023, 2024, 2025]

def build():
    specialty, s_cert, s_major, cutoff, applicants = [], [], [], [], []

    for code, name, duty, phys, itv, interest, base, note in SPECS:
        specialty.append({
            "specialty_code": f"{BRANCH[:1]}-{code}", "branch": BRANCH, "field": FIELD,
            "specialty_name": name, "duty": duty, "physical_grade": phys,
            "interview": itv, "interest_types": interest, "note": note,
        })
        for cname, grade in CERTS[code]:
            s_cert.append({"specialty_code": f"{BRANCH[:1]}-{code}",
                           "cert_name": cname, "cert_grade": grade})
        for m in MAJORS[code]:
            s_major.append({"specialty_code": f"{BRANCH[:1]}-{code}", "major_name": m})

        for y in YEARS:
            drift = (y - 2024) * random.uniform(-1.6, 1.6)
            for r in ROUNDS:
                score = round(base + drift + random.uniform(-2.4, 2.4), 1)
                picked = random.randint(8, 46)
                cutoff.append({
                    "year": y, "round": r, "branch": BRANCH,
                    "specialty_code": f"{BRANCH[:1]}-{code}",
                    "specialty_name_raw": name,      # 원본 이름 보존 (연결 오류 추적용)
                    "cutoff_score": score, "selected_count": picked,
                    "unit": "전군",
                })
                applicants.append({
                    "year": y, "round": r,
                    "specialty_code": f"{BRANCH[:1]}-{code}",
                    "planned_count": picked,
                    "applicant_count": int(picked * random.uniform(1.4, 4.2)),
                })

    interest_map = {s["specialty_code"]: s["interest_types"] for s in specialty}

    files = {
        "specialty.json": specialty, "specialty_cert.json": s_cert,
        "specialty_major.json": s_major, "cutoff.json": cutoff,
        "applicants.json": applicants, "interest_map.json": interest_map,
    }
    for fname, payload in files.items():
        p = OUT / fname
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        n = len(payload) if isinstance(payload, list) else len(payload.keys())
        print(f"  {fname:24s} {n:4d}건")

if __name__ == "__main__":
    print("샘플 데이터 생성 →", OUT)
    build()
    print("완료. web/index.html 을 열어 확인하세요.")
