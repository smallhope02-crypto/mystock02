"""API 키 및 기본 설정을 위한 구성 도우미."""
os를
 가져옵니다
데이터클래스 에서 데이터클래스
 가져오기


@dataclass
클래스 AppConfig :
 
    """키움 API 자격 증명 및 계좌 번호를 위한 간단한 컨테이너입니다."""

    앱 키: 문자열
    앱 시크릿: str
    계좌번호: str

    @클래스메서드
    def from_env ( cls ) -> "AppConfig" :
 
        """적절한 기본값을 사용하여 환경 변수에서 구성을 불러옵니다."""
        cls를 반환합니다 (
            app_key=os.getenv( "KIWOOM_APP_KEY" , "demo_app_key" ),
            app_secret=os.getenv( "SWEET_APP_SECRET" , "demo_app_secret" ),
            account_no=os.getenv("KIWOOM_ACCOUNT_NO" , "00000000" ),
        )
