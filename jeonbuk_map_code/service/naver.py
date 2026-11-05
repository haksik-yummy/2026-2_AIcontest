"""네이버 클라우드 Maps의 Directions 5를 서버에서 호출합니다.

인증키는 환경변수 NCP_MAPS_KEY_ID, NCP_MAPS_KEY로만 받습니다. 브라우저로 보내지 않고 파일에 쓰지 않습니다.
경로 응답은 요청을 처리하는 동안만 쓰고 저장하지 않습니다.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from store import ApiError

DIRECTIONS_URL = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
OPTIONS = ("traoptimal", "trafast", "tracomfort", "traavoidtoll", "traavoidcaronly")
ERROR_TEXT = {1: "출발지와 도착지가 같습니다", 2: "출발지 또는 도착지가 도로 주변이 아닙니다", 3: "자동차 길 찾기 결과를 제공할 수 없습니다",
              4: "경유지가 도로 주변이 아닙니다", 5: "경유지를 포함한 직선거리 합이 1,500km 이상입니다"}


def configured():
    return bool(os.environ.get("NCP_MAPS_KEY_ID") and os.environ.get("NCP_MAPS_KEY"))


def lonlat(text, name):
    """'경도,위도' 문자열을 검사한다. 국내 범위를 벗어나면 좌표가 뒤바뀐 경우가 많다."""
    try:
        lon, lat = (float(v) for v in str(text).split(","))
    except ValueError:
        raise ApiError(400, "bad_coordinate", f"{name}은 '경도,위도' 형식입니다 (예: 127.1,35.8)") from None
    if not (123 <= lon <= 132 and 32 <= lat <= 39.5):
        raise ApiError(400, "bad_coordinate", f"{name} 좌표가 국내 범위 밖입니다. 경도,위도 순서를 확인하세요")
    return lon, lat


def directions(start, goal, option="traoptimal", waypoints=None, timeout=15):
    """경로를 받아 {"distance_m", "duration_s", "path", "sections"}로 돌려준다."""
    if not configured():
        raise ApiError(503, "naver_not_configured", "서버에 NCP_MAPS_KEY_ID·NCP_MAPS_KEY 환경변수가 없어 Directions 5를 호출할 수 없습니다. "
                                                    "노선 구간 조회(/api/v1/route-risk/stretch)는 키 없이 쓸 수 있습니다")
    if option not in OPTIONS:
        raise ApiError(400, "bad_option", f"option은 {', '.join(OPTIONS)} 중 하나입니다")
    query = {"start": f"{start[0]},{start[1]}", "goal": f"{goal[0]},{goal[1]}", "option": option}
    if waypoints:
        if len(waypoints) > 5:
            raise ApiError(400, "too_many_waypoints", "경유지는 최대 5개입니다")
        query["waypoints"] = "|".join(f"{x},{y}" for x, y in waypoints)
    url = os.environ.get("NCP_MAPS_DIRECTIONS_URL", DIRECTIONS_URL) + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"x-ncp-apigw-api-key-id": os.environ["NCP_MAPS_KEY_ID"],
                                                   "x-ncp-apigw-api-key": os.environ["NCP_MAPS_KEY"]})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except ValueError:
            raise ApiError(502, "naver_error", f"Directions 5 응답 오류 HTTP {exc.code}") from None
        if exc.code in (401, 403):
            raise ApiError(502, "naver_auth", "Directions 5 인증에 실패했습니다. 키와 Maps 이용 신청을 확인하세요") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise ApiError(502, "naver_unreachable", f"Directions 5에 연결하지 못했습니다: {exc}") from None
    code = body.get("code")
    if code != 0:
        raise ApiError(422 if code in ERROR_TEXT else 502, "naver_route", ERROR_TEXT.get(code, body.get("message", "경로를 찾지 못했습니다")))
    try:
        route = body["route"][option][0]
        return {"distance_m": route["summary"]["distance"], "duration_s": route["summary"]["duration"] / 1000,  # 응답은 밀리초
                "path": route["path"], "sections": [{"name": s.get("name"), "distance_m": s.get("distance")} for s in route.get("section", [])]}
    except (KeyError, IndexError, TypeError):
        raise ApiError(502, "naver_format", "Directions 5 응답 형식이 예상과 다릅니다") from None
