# AI Generation Library · book-generator

**주제를 정하고, 당신의 AI로 한 권의 책을 작성하세요.** 사용자가 자신의 API 키로 실행하는 로컬 웹 화면과 CLI입니다. OpenAI·Claude·Gemini로 목차를 기획하고 장별 Markdown을 작성합니다. 완성된 원고는 [books](https://github.com/AI-Generation-Library/books)의 콘텐츠 형식으로 저장하며, 검토한 책은 [온라인 서재](https://ai-generation-library.github.io/library/)에 기여할 수 있습니다.

## 시작하기

Python **3.11 이상**이 필요합니다. Windows PowerShell:

```powershell
git clone https://github.com/AI-Generation-Library/book-generator.git
cd book-generator
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
book-generator serve
```

macOS·Linux에서는 가상환경 활성화 명령을 `source .venv/bin/activate`로 바꿉니다. PowerShell의 활성화가 제한된 환경에서는 `.venv\Scripts\python.exe -m pip install -e .`, `.venv\Scripts\python.exe -m book_generator serve`로 실행할 수 있습니다.

**[http://127.0.0.1:8090/](http://127.0.0.1:8090/)** 에서 책 제목·주제·독자·장 수를 정하고 제공자, 모델 ID, API 키를 입력합니다. 목차와 참고 자료를 추가할 수도 있습니다. 키 없이 **데모로 체험하기**를 누르면 실제 AI 호출 없이 예시 원고와 ZIP을 만듭니다.

웹 화면에는 작업별 진행률, 입력·출력 사용량, 중단·재개, 장 선택과 Markdown 미리보기, ZIP 다운로드가 있습니다. 서버는 `127.0.0.1`에서만 실행합니다. GitHub Pages에 호스팅하는 서비스가 아니라 사용자의 컴퓨터에서 실행하는 도구입니다.

## 지원하는 AI

| 제공자 | API | CLI 환경 변수 | 모델 확인 |
| --- | --- | --- | --- |
| OpenAI | Responses · 저장 옵션 `store: false` | `OPENAI_API_KEY` | [공식 모델 문서](https://developers.openai.com/api/docs/models) |
| Claude · Anthropic | Messages | `ANTHROPIC_API_KEY` | [공식 모델 문서](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Gemini · Google | generateContent | `GEMINI_API_KEY` | [공식 모델 문서](https://ai.google.dev/gemini-api/docs/models) |

모델은 자동 선택하지 않습니다. 계정에서 접근할 수 있는 **정확한 모델 ID**를 직접 입력하세요. 텍스트 생성과 요청한 출력 한도를 지원해야 하며, OpenAI 목차 생성에는 Structured Outputs를 지원하는 모델이 필요합니다. Gemini에는 `models/` 접두사를 제외한 ID를 입력합니다. 여러 Workspace에 접근하는 Anthropic 키는 선택 항목 `workspace_id`를 지정할 수 있습니다.

키에 연결된 제공자 계정으로 요청하며 비용과 사용량은 그 계정에 청구됩니다. 이 프로젝트에서 토큰을 제공하거나 중계 서버에서 비용을 대신 결제하지 않습니다.

## CLI로 생성하기

먼저 API 없이 실행 흐름을 확인합니다.

```powershell
book-generator generate --config examples/book.json --demo
```

실제 생성은 `examples/book.json`을 복사해 제목·주제·장 수, `provider`와 `model`을 수정한 뒤 실행합니다. `provider`는 `openai`, `claude`, `gemini` 중 하나입니다. **설정 JSON에 API 키를 넣지 마세요.**

```powershell
book-generator generate --config my-book.json
```

환경 변수가 없으면 CLI가 키를 숨김 입력으로 받습니다. 자동화에서는 위 표의 프로세스 환경 변수를 사용합니다. 키를 명령줄 인자로 받지 않습니다. `python -m book_generator`도 같은 명령을 지원합니다.

## 출력과 재개

```text
generated/<run-id>/
├── checkpoint.json                # 설정·진행·사용량, API 키 없음
├── plan.json                      # 생성한 목차
├── responses/                     # API 응답 원문, 실행하지 않음
├── book/<book-id>/
│   ├── book.json                   # 목차·출처·미검수 상태
│   ├── index.md                    # 책 소개와 목차
│   ├── 01-chapter/chapter.md       # 장별 원고
│   ├── …
│   ├── appendices/verification.md  # 실제 검증 범위
│   └── generation-input.json      # 입력 주제·목차·참고 자료
└── <book-id>.zip                   # 완성된 책만 포함
```

작업마다 독립된 폴더를 만듭니다. `--output <폴더>`로 저장 위치를 바꿀 수 있습니다. 웹 중단 버튼이나 CLI의 Ctrl+C로 중단한 뒤 키를 다시 입력해 재개합니다. 완성한 장은 다시 호출하지 않습니다. 저장한 원고를 수정했다면 덮어쓰지 않고 중단하므로, 수정본은 별도로 보관한 뒤 재개하세요.

```powershell
book-generator resume "generated/<run-id>" --output-budget 100000 --max-output-tokens 8000
book-generator validate "generated/<run-id>/book/<book-id>"
```

`max_output_tokens`는 호출당 출력 한도, `output_budget`는 작업 전체의 출력 예산입니다. 입력 토큰은 별도 과금되므로 **금액 한도가 아닙니다**. 추론 토큰이 응답 사용량에 포함되면 출력 사용량에 합산합니다. 다음 호출의 한도를 모두 예약할 수 없으면 중단합니다. 응답이 잘리거나 오류가 나면 원문과 진행 상태를 보존하며 자동 재시도하지 않습니다. 필요하면 한도를 늘려 재개하세요. 목차 형식 오류 시 재개는 목차를 다시 요청합니다.

취소·시간 초과·연결 오류 때 이미 시작한 호출은 과금될 수 있습니다. 사용량을 확인하지 못한 호출은 예약 출력 한도를 보수적으로 유지합니다. 새 API 키로 재개해도 이전 사용량이 초기화되지 않습니다.

## books에 기여하기

완성된 책의 사실·출처·예제·라이선스를 검토하고 실제 확인한 범위를 기록하세요. 생성기는 원고를 `draft`·`unreviewed`로 표시하며 코드 실행, URL 조회, 사람 검수를 수행했다고 주장하지 않습니다. 데모 원고는 데모임을 명시합니다.

```powershell
book-generator export "generated/<run-id>" --books "../books"
cd ../books
python scripts/validate-books.py
```

새 책을 `books/content/<book-id>/`에 복사합니다. 동일한 id가 이미 있으면 종료하며 Git commit·push·PR·웹 배포는 자동으로 수행하지 않습니다. 검토 후 [books 기여 안내](https://github.com/AI-Generation-Library/books/blob/main/CONTRIBUTING.md)에 따라 PR을 제출하세요. 책 목록은 `book.json`에서 서비스가 생성하므로 README에 목록을 추가할 필요가 없습니다.

## 키와 로컬 데이터

API 키는 실행 중 메모리에서 사용하고 작업 종료·중단 시 참조를 비웁니다. 키 입력은 전송 후 화면에서 지우며 브라우저 저장소·설정·체크포인트·ZIP·애플리케이션 로그에 저장하지 않습니다. 키와 함께 입력한 **책 주제·목차·참고 자료는 선택한 AI 제공자로 전송**됩니다. 그 입력과 생성 원고는 로컬 작업 폴더에 남습니다. 제공자의 데이터 처리 정책은 별도로 적용됩니다.

생성 폴더, 가상환경, 실제 `.env` 파일은 Git에서 제외합니다. 공유할 때는 내용을 검토한 원고 ZIP만 사용하세요. 로컬 웹 화면은 Host 검사·동일 출처 확인·요청 토큰으로 보호하며 외부 CORS를 허용하지 않습니다.

## 개발과 검사

```powershell
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m pytest -q
```

테스트는 제공자별 HTTP 요청·사용량·오류·응답 잘림, 예산 중단과 재개, 취소와 키 처리, 파일 보호, 실제 books 검증기와의 호환, 웹 API와 CLI를 확인합니다. CI는 Python 3.11·3.12에서 실행하며 API 키나 유료 호출이 필요 없습니다. 현재 검증은 모의 HTTP 응답과 오프라인 데모 기반입니다. 실제 계정별 모델 권한·속도·과금과 실시간 API 호출은 검증하지 않았습니다.

소프트웨어는 [MIT](LICENSE)입니다. 포함한 books 콘텐츠 검증기는 원본의 CC0 조건을 따릅니다. 생성 원고를 공개할 때 적용할 라이선스와 제삼자 자료의 권리는 기여자가 확인합니다.
