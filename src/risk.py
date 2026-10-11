"""결빙 위험도 기준표 및 구간별 위험도 산출."""


def find_icing_conditions(df):
    """결빙 발생 관련 기상영향인자와 환경조건(임계값 등)을 도출한다."""
    raise NotImplementedError


def build_risk_criteria(conditions):
    """요인별(기상, 도로, 지형) 위험영향 수준과 기준 설정 근거를 담은 기준표를 만든다."""
    raise NotImplementedError


def score_segments(segments, criteria):
    """구간별 결빙 위험도(점수·등급)를 산출한다."""
    raise NotImplementedError


def compare_with_vulnerable_sections(scored_segments, vulnerable_sections):
    """기존 전북도 결빙취약구간(22개소)과 산출 결과를 비교한다."""
    raise NotImplementedError
