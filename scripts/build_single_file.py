# -*- coding: utf-8 -*-
"""
web/index.html 을 데이터까지 넣은 '파일 하나짜리' 화면으로 묶습니다.

왜 필요한가:
  web/index.html 은 JSON 파일을 따로 읽어오기 때문에 서버로 열어야 합니다.
  이 스크립트로 만든 docs/시제품.html 은 더블클릭만으로 열립니다.
  (메일로 보내거나 상담용 노트북에 복사할 때 편합니다)

실행:  python3 scripts/build_single_file.py
"""
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = ["specialty","cert_index","major_index","spec_cert_index","jiwon_stats",
         "cutoff","applicants","interest_map"]

def trim(data):
    """상담 화면이 쓰는 212개 특기에 해당하는 부분만 남깁니다.

    병무청 API 색인에는 화면 목록에 없는 특기(약 500개)까지 들어 있어
    그대로 넣으면 파일 하나짜리 화면이 수십 MB 가 됩니다. 더블클릭으로 열기
    어려워지므로, 화면이 실제로 점수를 매기는 특기만 남겨 크기를 줄입니다.
    """
    keep = {s["specialty_code"] for s in data["specialty"]}

    data["major_index"] = {
        name: [c for c in codes if c in keep]
        for name, codes in data["major_index"].items()}
    data["major_index"] = {k: v for k, v in data["major_index"].items() if v}

    data["cert_index"] = {
        name: [r for r in rows if r["specialty_code"] in keep]
        for name, rows in data["cert_index"].items()}
    data["cert_index"] = {k: v for k, v in data["cert_index"].items() if v}

    data["spec_cert_index"] = {k: v for k, v in data["spec_cert_index"].items() if k in keep}
    data["jiwon_stats"]     = {k: v for k, v in data["jiwon_stats"].items() if k in keep}
    return data


def main():
    data = {f: json.loads((ROOT/"data"/"build"/f"{f}.json").read_text(encoding="utf-8")) for f in FILES}
    data = trim(data)
    data["rules"] = json.loads((ROOT/"rules"/"2026-army-tech.json").read_text(encoding="utf-8"))

    html = (ROOT/"web"/"index.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    inject = "<script>window.__EMBEDDED__=" + blob.replace("</", "<\\/") + ";</script>\n"

    marker = "<script>\n/* ========"
    assert marker in html, "web/index.html 구조가 바뀌었습니다. marker 를 확인하세요."
    out = html.replace(marker, inject + marker, 1)

    dest = ROOT/"docs"/"시제품.html"
    dest.write_text(out, encoding="utf-8")
    print(f"생성 완료: {dest}  ({len(out)/1024:.0f} KB)")
    print("→ 파일을 더블클릭하면 바로 열립니다.")

if __name__ == "__main__":
    main()
