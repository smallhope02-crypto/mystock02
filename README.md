
 자동매매 프로젝트 초기 설정용 README 입니다.
+
+## 실행 방법
+1. 저장소 루트(이 README가 있는 폴더)에서 가상환경을 활성화하고 의존성을 설치합니다.
+   - `pip install -r requirements.txt` (PyQt5가 없다면 `pip install pyqt5`)
+2. GUI 실행
+   - 기본: `python -m src.gui_main`
+   - 위 명령이 환경에 따라 `ModuleNotFoundError: No module named 'src'` 로 실패한다면 `python run_gui.py` 를 사용하세요. 이 스크립트는 저장소 루트를 PYTHONPATH에 자동으로 추가합니다.
+
+**Troubleshooting**
+
+- `SyntaxError: from __future__ import annotations` 가 보인다면 예전 버전의 코드를 실행하고 있을 가능성이 높습니다. 저장소를 최신 커밋으로 업데이트한 뒤 다시 실행해 주세요.
+- Python 3.8 이상을 사용하는지 확인하세요. GUI는 3.8 미만에서는 시작 시 종료 메시지를 출력하고 종료합니다.
+
+PyQt5가 설치되어 있지 않으면 프로그램이 종료되며 설치 방법을 안내하는 메시지를 출력합니다.
 
EOF
)
