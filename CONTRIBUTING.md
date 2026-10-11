# 기여 안내

버그와 기능 제안은 이 저장소의 Issues로, 구현은 PR로 제출해 주세요. API 키, `.env`, 개인 원고, 제공자 응답에 포함된 비공개 자료를 이슈나 테스트에 첨부하지 마세요. 재현은 키 없는 데모 또는 가짜 HTTP 응답으로 구성합니다.

## 개발

Python 3.11 이상에서 가상환경을 만들고 `python -m pip install -e ".[dev]"`를 실행합니다. `python -m ruff check src tests`와 `python -m pytest -q`로 검사합니다. CI는 실제 AI API를 호출하지 않습니다.

| 경로 | 역할 |
| --- | --- |
| `models.py`, `prompts.py` | 입력 설정과 목차·집필 요청 |
| `providers.py` | 제공자별 인증·요청·응답·토큰 사용량 |
| `engine.py`, `storage.py` | 예산, 체크포인트, 취소·재개, 경로와 파일 보호 |
| `manuscript.py`, `book_metadata.py` | books 콘텐츠 계약과 원고·ZIP·내보내기 |
| `web.py`, `static/` | 로컬 웹 API와 화면 |
| `cli.py` | 같은 생성 파이프라인을 사용하는 CLI |

제공자 오류 응답이나 요청 객체 전체를 로그·오류 메시지에 넣지 마세요. 자동 재시도는 추가 과금과 중복 생성을 유발하므로 기본 동작으로 추가하지 않습니다. 체크포인트에는 키를 기록하지 않습니다. 완성한 원고와 사용자가 수정한 파일을 보존합니다.

콘텐츠 계약은 [books/CONTENT-FORMAT.md](https://github.com/AI-Generation-Library/books/blob/main/CONTENT-FORMAT.md)를 따릅니다. 포함한 검증기를 변경하면 원본과의 호환을 확인하세요. CI가 books를 따로 가져와 실제 검증기로 생성물을 검사합니다. 책 추가·설명 수정은 books에, 읽기 화면·검색·배포 변경은 library에 PR을 제출합니다.
