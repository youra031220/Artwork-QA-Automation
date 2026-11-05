# 아트웍 검수 자동화 — 텍스트 추출 MVP

이 프로젝트는 아트웍 PDF에서 **원본 텍스트와 한국어 OCR 판독 후보**를 추출·비교하는 로컬 Streamlit 앱입니다. 이 단계에서는 검수 조건 판정과 로고 인식을 구현하지 않았습니다.

## 실행 방법 (Windows)

1. Python 3.10 이상을 설치합니다.
2. [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)를 설치하고 설치 경로를 Windows PATH에 등록합니다. `kor.traineddata`, `eng.traineddata` 언어팩도 설치합니다.
3. 저장소를 복제한 뒤 터미널에서 실행합니다.

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

4. 브라우저에서 PDF 여러 개를 업로드하고 OCR 범위를 선택합니다. 추출을 마치면 CSV·JSON·TXT 결과 ZIP을 다운로드할 수 있습니다.

## 작동 방식

- PyMuPDF로 PDF의 원본 텍스트와 위치 좌표를 읽습니다.
- 한국어가 포함되거나 텍스트가 깨진 줄을 이미지로 렌더링하고 Tesseract `kor+eng` OCR을 실행합니다.
- OCR은 원본 방향과 180도 회전 방향을 비교합니다.
- OCR 결과를 원문 옆에 **후보**로 보여줍니다. 원본을 자동으로 덮어쓰지 않습니다.
- 외부 AI API 호출은 없습니다.

## 내보내는 파일

- `extracted_lines.csv`: 원문, OCR, 페이지, 좌표, 검토 필요 여부
- `extracted_lines.json`: 동일한 데이터의 JSON
- `comparison.txt`: 원문과 OCR의 비교 텍스트
- `summary.json`: 파일별 페이지·줄 수 요약

## 현재 한계

- 문구 단위 OCR 오인식이 발생할 수 있습니다. 숫자·보증기간·주요 문구는 원본과 비교해야 합니다.
- `ocr_score_heuristic`은 회전 방향을 선택하기 위한 내부 점수이며 정확도 확률이 아닙니다.
- 스캔 이미지 전용 PDF처럼 텍스트 레이어가 아예 없는 파일은 현재 지원하지 않습니다.
- 로고·QR 검출, 인증마크 판정, 검수 규칙 적용 및 Gemini 연동은 미구현입니다.

## 데이터 보안

원본 회사 PDF, 승인 문구 Excel, 생성된 검수 결과, API 키는 저장소에 업로드하지 마세요. 업로드 PDF는 앱 프로세스에서만 처리하도록 설계되어 있으며 서버 배포 시 접근 통제를 별도로 고려해야 합니다.
