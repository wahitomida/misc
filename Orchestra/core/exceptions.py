"""AI Orchestra のカスタム例外定義。

全例外は ``OrchestraError`` を頂点とする階層に属する。API 関連の例外は
``OrchestraAPIError`` を経由してさらに分類される。

Note:
    Python 組み込みの ``TimeoutError`` を上書きしないよう、本モジュールでは
    ``OrchestraTimeoutError`` を ``TimeoutError`` という別名でも公開する。
    実装ガイドの命名 (``TimeoutError(OrchestraAPIError)``) との整合性を保つため。
"""

from __future__ import annotations

# --- 基底例外 ---------------------------------------------------------------


class OrchestraError(Exception):
    """AI Orchestra 全例外の基底クラス。"""


class OrchestraAPIError(OrchestraError):
    """API 呼び出しに関連する例外の基底クラス。"""


# --- API 系例外 -------------------------------------------------------------


class ModelNotFoundError(OrchestraAPIError):
    """指定モデルが利用不可・未配布。

    Attributes:
        model: 該当モデル名。
    """

    def __init__(self, model: str, message: str | None = None) -> None:
        self.model = model
        super().__init__(message or f"Model not found or unavailable: {model}")


class AuthenticationError(OrchestraAPIError):
    """認証失敗。レートリミットによる 401/403 と通常の認証エラーを区別する。

    Attributes:
        is_rate_limit: True の場合、レートリミット起因の認証拒否。
    """

    def __init__(self, message: str = "Authentication failed", is_rate_limit: bool = False) -> None:
        self.is_rate_limit = is_rate_limit
        super().__init__(message)


class RateLimitExhaustedError(OrchestraAPIError):
    """日次リクエスト上限に到達した。"""


class EmptyResponseError(OrchestraAPIError):
    """API は成功したが ``content`` が空文字列だった。"""


class MaxRetriesExceededError(OrchestraAPIError):
    """リトライ回数の上限を超えた。"""


class TimeoutError(OrchestraAPIError):  # noqa: A001 - 仕様で名前固定
    """API 呼び出しがタイムアウトした。

    Note:
        Python 組み込みの ``TimeoutError`` (``OSError`` のサブクラス) とは別物。
        モジュール内で利用する場合は ``orchestra_exceptions.TimeoutError`` のように
        修飾参照すること。
    """


class ServerError(OrchestraAPIError):
    """サーバ側エラー (5xx 系)。

    Attributes:
        status_code: HTTP ステータスコード。
        retryable: リトライによって回復しうるかどうか。
    """

    def __init__(self, status_code: int, message: str | None = None, retryable: bool = True) -> None:
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message or f"Server error: HTTP {status_code}")


# --- ロール / セッション / 入力検証 / チェーン / 設定 -----------------------


class RoleNotFoundError(OrchestraError):
    """指定された ``role_id`` が ``config/roles/`` に存在しない。"""


class RoleValidationError(OrchestraError):
    """ロール YAML の検証に失敗した (必須フィールド欠落など)。"""


class RoleProtectedError(OrchestraError):
    """デフォルトロールへの削除他禁止操作を試みた。"""


class SessionNotFoundError(OrchestraError):
    """指定セッション ID の出力ディレクトリが存在しない。"""


class InputTooShortError(OrchestraError):
    """ユーザー入力が短すぎる。"""


class InputTooLongError(OrchestraError):
    """ユーザー入力が長すぎる。"""


class ChainTooDeepError(OrchestraError):
    """フォローアップチェーンの深度が上限を超えた。"""


class ConfigLoadError(OrchestraError):
    """設定ファイルの読み込みに失敗した。"""


class PlanValidationError(OrchestraError):
    """指揮者が返した計画のパース・検証に失敗した。"""


class TooManyAttachmentsError(OrchestraError):
    """添付ファイル数が ``AttachmentProcessor.MAX_FILES`` を超えた。"""


class UnsupportedFileTypeError(OrchestraError):
    """添付ファイルの拡張子が許容リストにない。"""


class FileTooLargeError(OrchestraError):
    """添付ファイルのサイズが ``AttachmentProcessor.MAX_FILE_SIZE`` を超えた。"""


__all__ = [
    "OrchestraError",
    "OrchestraAPIError",
    "ModelNotFoundError",
    "AuthenticationError",
    "RateLimitExhaustedError",
    "EmptyResponseError",
    "MaxRetriesExceededError",
    "TimeoutError",
    "ServerError",
    "RoleNotFoundError",
    "RoleValidationError",
    "RoleProtectedError",
    "SessionNotFoundError",
    "InputTooShortError",
    "InputTooLongError",
    "ChainTooDeepError",
    "ConfigLoadError",
    "PlanValidationError",
    "TooManyAttachmentsError",
    "UnsupportedFileTypeError",
    "FileTooLargeError",
]
