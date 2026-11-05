"use strict";
// 지도 화면: API를 읽어 네이버 지도(키가 있을 때) 또는 내장 지도에 같은 결과를 그립니다.
(async () => {
  const CONFIG = window.ICING_CONFIG || {};
  const $ = id => document.getElementById(id);
  const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const GRADES = ["관심", "주의", "경계", "심각"];
  const GRADE_TOKEN = { "관심": "--good", "주의": "--warning", "경계": "--serious", "심각": "--critical" };
  const GRADE_WIDTH = { "관심": 3, "주의": 4, "경계": 5, "심각": 6 };
  const STATE_TOKEN = ["--state-none", "--warning", "--serious", "--critical"];
  const STATE_LABEL = ["조건 미충족", "결빙 가능 조건", "모델 예측만", "결빙 가능 조건 + 모델 예측"];
  const STATE_WIDTH = [3, 5, 5, 6];
  const CCTV_LABEL = { 0: "맑음", 11: "안개 약", 12: "안개 중", 13: "안개 강", 21: "비 약", 22: "비 중", 23: "비 강", 31: "눈 약", 32: "눈 중", 33: "눈 강" };

  function node(tag, props = {}, text) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else e.setAttribute(k, v);
    }
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  async function api(path, options) {
    const res = await fetch(path, options);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error?.message || `요청 실패 (HTTP ${res.status})`);
    return body;
  }
  const fmtT = v => (v === null || v === undefined) ? "자료 없음" : `${v.toFixed(1)}°C`;
  const fmtTime = t => t ? t.slice(0, 16).replace("T", " ") : "-";

  // ---------- 색 ----------
  let tempScale;
  function readColors() {
    const cold = token("--div-cold"), mid = token("--div-mid"), warm = token("--div-warm");
    tempScale = d3.scaleDiverging([-8, 0, 8], t => t < .5 ? d3.interpolateLab(cold, mid)(t * 2) : d3.interpolateLab(mid, warm)((t - .5) * 2)).clamp(true);
  }
  readColors();

  // ---------- 내장 지도 (키 없이, 인터넷 없이) ----------
  class SvgMap {
    constructor(el, segments, geo, on) {
      this.el = el; this.segments = segments; this.geo = geo; this.on = on; this.t = d3.zoomIdentity;
      this.tip = node("div", { class: "tip", hidden: "" }); el.append(this.tip);
      this.draw();
      new ResizeObserver(() => { if (Math.abs(el.clientWidth - this.w) > 1 || Math.abs(el.clientHeight - this.h) > 1) this.draw(); }).observe(el);
    }
    draw() {
      const { el, geo, segments } = this;
      if (this.svg && (el.clientWidth < 100 || el.clientHeight < 100)) return;  // 인쇄·화면 캡처 중 잠깐 작아질 때는 그대로 둔다
      this.w = el.clientWidth || 800; this.h = el.clientHeight || 600;
      d3.select(el).select("svg").remove();
      const svg = this.svg = d3.select(el).insert("svg", ":first-child").attr("viewBox", `0 0 ${this.w} ${this.h}`).attr("role", "img").attr("aria-label", "구간 지도");
      const focus = { type: "FeatureCollection", features: geo.features.filter(f => String(f.properties.code).startsWith("35")) };
      this.proj = d3.geoMercator().fitExtent([[14, 14], [this.w - 14, this.h - 14]], focus);
      this.path = d3.geoPath(this.proj);
      const g = this.g = svg.append("g");
      g.append("g").selectAll("path").data(geo.features).join("path").attr("class", f => "region" + (String(f.properties.code).startsWith("35") ? " main" : "")).attr("d", this.path);
      g.append("g").selectAll("text").data(focus.features.filter(f => f.properties.name !== "전주시덕진구")).join("text").attr("class", "city")
        .attr("text-anchor", "middle").attr("transform", f => `translate(${this.path.centroid(f)})`).text(f => f.properties.name.replace("전주시완산구", "전주"));
      this.overlay = g.append("g");
      this.casing = g.append("g").selectAll("path").data(segments).join("path").attr("class", "seg-casing").attr("d", this.path);
      this.lines = g.append("g").selectAll("path").data(segments).join("path").attr("class", "seg-line").attr("d", this.path);
      this.routeG = g.append("g");
      this.sel = g.append("path").attr("class", "sel-line");
      g.append("g").selectAll("path").data(segments).join("path").attr("class", "seg-hit").attr("d", this.path)
        .on("click", (ev, f) => { if (!this.picking) this.on.select(f.properties.seg_id); })
        .on("pointermove", (ev, f) => this.showTip(ev, this.on.tip(f.properties.seg_id)))
        .on("pointerleave", () => { this.tip.hidden = true; });
      this.stG = g.append("g");
      this.ptG = g.append("g");
      svg.on("click.pick", ev => {
        if (!this.picking || ev.defaultPrevented) return;
        const [x, y] = this.t.invert(d3.pointer(ev, svg.node()));
        const [lon, lat] = this.proj.invert([x, y]);
        const cb = this.picking; this.picking = null; cb(lon, lat);
      });
      this.zoom = d3.zoom().scaleExtent([1, 14]).clickDistance(5).on("zoom", ev => {
        this.t = ev.transform; g.attr("transform", this.t); this.placeMarks();
        g.selectAll(".city").style("font-size", `${12 / this.t.k}px`).style("stroke-width", `${3 / this.t.k}px`);
      });
      svg.call(this.zoom).call(this.zoom.transform, this.t);
      if (this.last) this.paint(this.last);
      if (this.lastStations) this.setStations(...this.lastStations);
      if (this.lastRoute) this.showRoute(this.lastRoute);
      if (this.lastOverlay) this.setOverlay(this.lastOverlay);
      if (this.lastPoints) this.setPoints(this.lastPoints);
    }
    showTip(ev, text) {
      const box = this.el.getBoundingClientRect();
      this.tip.textContent = text; this.tip.hidden = false;
      const x = Math.min(ev.clientX - box.left + 12, box.width - this.tip.offsetWidth - 4);
      this.tip.style.left = `${Math.max(0, x)}px`; this.tip.style.top = `${ev.clientY - box.top + 12}px`;
    }
    paint(style) {
      this.last = style;
      this.lines.attr("stroke", f => style(f.properties.seg_id).color).attr("stroke-width", f => style(f.properties.seg_id).width);
      this.casing.attr("stroke-width", f => style(f.properties.seg_id).width + 2.5);
    }
    select(segId) {
      const f = this.segments.find(s => s.properties.seg_id === segId);
      this.sel.attr("d", f ? this.path(f) : null).attr("stroke-width", 13);
    }
    placeMarks() {
      const k = this.t.k;
      this.stG.selectAll("path").attr("transform", s => `translate(${this.proj([s.lon, s.lat])}) scale(${1 / k})`);
      this.ptG.selectAll("circle").attr("transform", p => `translate(${this.proj([p.lon, p.lat])}) scale(${1 / k})`);
    }
    setStations(list, fill) {
      this.lastStations = [list, fill];
      this.stG.selectAll("path").data(list, s => s.stn).join("path").attr("class", "station")
        .attr("d", s => d3.symbol().type(s.holdout ? d3.symbolDiamond : d3.symbolSquare).size(s.holdout ? 150 : 95)()).attr("fill", fill)
        .on("click", (ev, s) => { if (!this.picking) this.on.select(s.seg_id); })
        .on("pointermove", (ev, s) => this.showTip(ev, this.on.stationTip(s)))
        .on("pointerleave", () => { this.tip.hidden = true; });
      this.placeMarks();
    }
    setPoints(items) {
      this.lastPoints = items;
      this.ptG.selectAll("circle").data(items).join("circle").attr("class", "pin").attr("r", 4)
        .on("pointermove", (ev, p) => this.showTip(ev, p.label)).on("pointerleave", () => { this.tip.hidden = true; });
      this.placeMarks();
    }
    setOverlay(geojson) {
      this.lastOverlay = geojson;
      this.overlay.selectAll("path").data(geojson ? geojson.features : []).join("path").attr("class", "vuln").attr("d", this.path);
    }
    showRoute(lines) {
      this.lastRoute = lines;
      this.routeG.selectAll("path").data(lines ? [{ type: "MultiLineString", coordinates: lines }] : []).join("path").attr("class", "route-line").attr("d", this.path);
    }
    pick(cb) { this.picking = cb; }
  }

  // ---------- 네이버 지도 (공개 Client ID만 씀) ----------
  function loadNaverSdk(keyId) {
    return new Promise((resolve, reject) => {
      if (window.naver?.maps?.Map) { resolve(window.naver.maps); return; }
      window.navermap_authFailure = () => { window.__naverAuthFailed = true; reject(new Error("네이버 지도 인증에 실패했습니다")); };
      const s = document.createElement("script");
      s.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(keyId)}`;
      s.onload = () => window.naver?.maps ? resolve(window.naver.maps) : reject(new Error("네이버 지도 스크립트를 읽지 못했습니다"));
      s.onerror = () => reject(new Error("네이버 지도 스크립트를 읽지 못했습니다"));
      document.head.append(s);
    });
  }

  class NaverMap {
    constructor(el, maps, segments, on) {
      this.maps = maps; this.on = on; this.markers = []; this.points = []; this.overlays = [];
      this.segments = segments;
      this.map = new maps.Map(el, { center: new maps.LatLng(35.75, 127.1), zoom: 9 });
      this.map.data.addGeoJson({ type: "FeatureCollection", features: segments });
      this.map.data.addListener("click", e => { if (!this.picking) this.on.select(e.feature.getProperty("seg_id")); });
      maps.Event.addListener(this.map, "click", e => {
        if (!this.picking) return;
        const ll = e.coord || e.latlng, cb = this.picking; this.picking = null; cb(ll.lng(), ll.lat());
      });
    }
    paint(style) {
      this.style = style;
      this.map.data.setStyle(f => {
        const id = f.getProperty("seg_id"), s = style(id);
        return { strokeColor: s.color, strokeWeight: s.width + (id === this.selected ? 3 : 0), strokeOpacity: 1 };
      });
    }
    select(segId) { this.selected = segId; if (this.style) this.paint(this.style); }
    setStations(list, fill) {
      this.markers.forEach(m => m.setMap(null));
      const { maps } = this;
      this.markers = list.map(s => {
        const mark = node("div", { style: `width:12px;height:12px;background:${fill(s)};border:2px solid #fff;${s.holdout ? "transform:rotate(45deg);" : ""}` });
        const m = new maps.Marker({ position: new maps.LatLng(s.lat, s.lon), map: this.map, title: this.on.stationTip(s),
          icon: { content: mark.outerHTML, anchor: new maps.Point(8, 8) } });
        maps.Event.addListener(m, "click", () => this.on.select(s.seg_id));
        return m;
      });
    }
    setPoints(items) {
      this.points.forEach(m => m.setMap(null));
      const { maps } = this;
      this.points = items.map(p => new maps.Marker({ position: new maps.LatLng(p.lat, p.lon), map: this.map, title: p.label,
        icon: { content: '<div style="width:9px;height:9px;border-radius:50%;background:#0b0b0b;border:2px solid #fff"></div>', anchor: new maps.Point(6, 6) } }));
    }
    setOverlay(geojson) {
      this.overlays.forEach(p => p.setMap(null));
      const { maps } = this;
      this.overlays = (geojson ? geojson.features : []).flatMap(f => {
        const lines = f.geometry.type === "LineString" ? [f.geometry.coordinates] : f.geometry.coordinates;
        return lines.map(line => new maps.Polyline({ map: this.map, path: line.map(([x, y]) => new maps.LatLng(y, x)), strokeColor: "#0b0b0b", strokeOpacity: .2, strokeWeight: 14 }));
      });
    }
    showRoute(lines) {
      (this.routes || []).forEach(p => p.setMap(null));
      const { maps } = this;
      this.routes = (lines || []).map(line => new maps.Polyline({ map: this.map, path: line.map(([x, y]) => new maps.LatLng(y, x)),
        strokeColor: "#2a78d6", strokeWeight: 4, strokeOpacity: .9 }));
    }
    pick(cb) { this.picking = cb; }
  }

  // ---------- 화면 상태 ----------
  const view = { mode: "history", color: "state", at: null, selected: null, records: new Map(), stations: [], status: null };
  let meta, segments, map, liveTimer = null, requestNo = 0;

  const on = {
    select: id => selectSegment(id),
    tip: id => {
      const f = segById(id).properties, r = view.records.get(id);
      return `${id} · ${f.grade} · ${r ? `${fmtT(r.rst_est)} · ${r.status.label}` : "자료 없음"}`;
    },
    stationTip: s => {
      const o = view.stations.find(x => x.stn === s.stn);
      return `${s.name}${s.holdout ? "(검증 지점)" : ""} · 실측 ${fmtT(o?.rst ?? null)} · ${o?.road_state?.label ?? "자료 없음"}`;
    },
  };
  const segById = id => segments.find(f => f.properties.seg_id === id);

  function segStyle(id) {
    const f = segById(id).properties, r = view.records.get(id);
    if (view.color === "grade") return { color: token(GRADE_TOKEN[f.grade]), width: GRADE_WIDTH[f.grade] };
    if (!r || r.state === null || r.state === undefined) return { color: token("--no-data"), width: 3 };
    if (view.color === "rst") return r.rst_est === null ? { color: token("--no-data"), width: 3 } : { color: tempScale(r.rst_est), width: 5 };
    return { color: token(STATE_TOKEN[r.state]), width: STATE_WIDTH[r.state] };
  }
  function stationFill(s) {
    const o = view.stations.find(x => x.stn === s.stn);
    if (view.color === "grade" || !o) return token("--station");
    if (view.color === "rst") return o.rst === null ? token("--surface") : tempScale(o.rst);
    return o.icing_related_observed ? token("--critical") : o.road_state.value === null ? token("--surface") : token("--state-none");
  }

  function renderLegend() {
    const lg = $("legend"); lg.replaceChildren();
    const item = (style, text, cls = "key") => { const s = node("span", { class: "item" }); s.append(node("span", { class: cls, style }), document.createTextNode(text)); lg.append(s); };
    if (view.color === "grade") {
      lg.append(node("b", {}, "위험 등급"));
      GRADES.forEach(g => item(`background:${token(GRADE_TOKEN[g])};height:${GRADE_WIDTH[g]}px`, `${g} ${meta.grade_counts[g]}`));
    } else if (view.color === "rst") {
      lg.append(node("b", {}, "추정 노면온도"));
      item(`background:linear-gradient(90deg,${tempScale(-8)},${tempScale(0)},${tempScale(8)});width:90px;height:10px`, "-8 ~ 0 ~ 8°C", "key box");
    } else {
      lg.append(node("b", {}, "결빙 가능 조건"));
      [0, 1, 3, 2].forEach(s => item(`background:${token(STATE_TOKEN[s])};height:${STATE_WIDTH[s]}px`, STATE_LABEL[s]));
    }
    item(`background:${token("--no-data")};height:3px`, "자료 없음");
    item(`background:${token("--station")}`, "RWIS", "key box");
    if (meta.vulnerable_sections) item(`background:${token("--band")};height:10px`, "상습 결빙구간");
  }

  function repaint() {
    map.paint(segStyle);
    map.setStations(stationsMeta, stationFill);
    renderLegend();
  }

  function renderSummary(s) {
    const box = $("summary"); box.replaceChildren();
    [["결빙 가능 조건", `${s.summary.condition}구간`], ["모델 예측", `${s.summary.prediction}구간`], ["최저 추정 노면", fmtT(s.summary.min_rst)]].forEach(([k, v]) => {
      const d = node("div", { class: "stat" }); d.append(node("b", {}, v), node("span", {}, k)); box.append(d);
    });
    const note = $("summary-note");
    if (s.mode === "live") {
      const f = s.freshness;
      note.textContent = f.state === "fresh" ? `${s.source} · 수신 후 ${f.age_minutes.toFixed(0)}분 경과 · 신선도 기준 ${f.ttl_minutes}분`
        : f.state === "stale" ? `마지막 수신 ${fmtTime(f.valid_time)}이 기준 ${f.ttl_minutes}분보다 오래되어 회색으로 표시합니다. 현재 상태를 알 수 없습니다.`
          : "수신 자료가 없어 회색으로 표시합니다. 현재 날씨나 결빙을 임의로 만들지 않습니다.";
    } else note.textContent = "제출 분석 결과의 과거 재생입니다. 현재 상태가 아닙니다.";
  }

  function renderSelected() {
    const box = $("selected"); box.replaceChildren();
    if (!view.selected) { box.append(node("p", { class: "note" }, "지도에서 구간을 누르세요.")); return; }
    const f = segById(view.selected).properties, r = view.records.get(view.selected);
    const g = node("div", { class: "grade" });
    g.append(node("span", { class: "key box", style: `background:${token(GRADE_TOKEN[f.grade])}` }), document.createTextNode(`${f.seg_id} · ${f.grade}`));
    const dl = node("dl", { class: "kv" });
    [["노선", `${f.route} ${f.km_from.toFixed(1)}~${f.km_to.toFixed(1)}km`], ["시군", f.sigungu], ["위험 총점", `${f.score.toFixed(2)} / 4`],
      ["추정 노면온도", fmtT(r?.rst_est ?? null)], ["상태", r?.status?.label ?? "자료 없음"], ["자료 시각", fmtTime(view.status?.data_time)]].forEach(([k, v]) => dl.append(node("dt", {}, k), node("dd", {}, v)));
    const act = node("div", { class: "actions" });
    const app = node("button", { type: "button" }, "네이버 지도 앱에서 열기");
    app.onclick = () => openPlace(f, r);
    const atlas = node("a", { href: `/atlas#seg=${encodeURIComponent(f.seg_id)}${view.status?.data_time && view.mode === "history" ? `&t=${view.status.data_time.slice(0, 13)}&mode=state` : ""}`, target: "_blank", rel: "noopener" }, "분석 지도에서 보기");
    act.append(app, atlas);
    box.append(g, dl, act);
  }

  async function selectSegment(id) {
    view.selected = id;
    map.select(id);
    renderSelected();
  }

  // ---------- 네이버 앱 호출 ----------
  const appName = () => location.origin + location.pathname;
  const isAndroid = () => /Android/i.test(navigator.userAgent);
  const isIos = () => /iPhone|iPad|iPod/i.test(navigator.userAgent);
  function launchApp(action, query) {
    const q = Object.entries({ ...query, appname: appName() }).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    if (isAndroid()) { location.href = `intent://${action}?${q}#Intent;scheme=nmap;action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;package=com.nhn.android.nmap;end`; return; }
    const url = `nmap://${action}?${q}`;
    if (isIos()) {
      const t0 = Date.now();
      location.href = url;
      setTimeout(() => { if (!document.hidden && Date.now() - t0 < 2000) location.href = "https://itunes.apple.com/app/id311867728?mt=8"; }, 1500);
      return;
    }
    showBanner(`휴대폰의 네이버 지도 앱에서만 열립니다. 호출 주소: ${url}`);
  }
  function openPlace(f, r) {
    const kind = view.mode === "live" ? "현재" : "과거";
    launchApp("place", { lat: f.lat, lng: f.lon, name: `${f.seg_id} ${f.grade} ${r?.status?.label ?? "자료 없음"} (${kind} ${fmtTime(view.status?.data_time)})` });
  }
  function showBanner(text) { const b = $("banner"); b.textContent = text; b.hidden = !text; }

  // ---------- 자료 읽기 ----------
  function statusUrl() {
    return view.mode === "live" ? "/api/v1/status?mode=live" : `/api/v1/status?${new URLSearchParams({ mode: "history", at: view.at })}`;
  }
  async function refresh() {
    const no = ++requestNo;
    $("data-time").textContent = "읽는 중…";
    try {
      const s = await api(statusUrl());
      if (no !== requestNo) return;
      view.status = s;
      view.records = new Map(s.segments.map(r => [r.seg_id, r]));
      view.stations = s.stations;
      $("data-time").textContent = s.data_time ? `${s.mode === "live" ? "현재 수신" : "과거 재생"} ${fmtTime(s.data_time)} KST` : "수신 자료 없음";
      renderSummary(s);
      showBanner(CONFIG.simulatedClock && view.mode === "live" ? `시연 시각 사용 중입니다 (서버 시각 ${fmtTime(s.now)}). 실제 현재가 아닙니다.` : "");
    } catch (err) {
      if (no !== requestNo) return;
      // 읽지 못한 값을 이전 화면으로 남기지 않는다
      view.status = null; view.records = new Map(); view.stations = [];
      $("data-time").textContent = "자료를 읽지 못함";
      $("summary").replaceChildren();
      $("summary-note").textContent = err.message;
    }
    repaint();
    renderSelected();
    renderBriefing();
    if (view.mode === "live") refreshCctv();
    else map.setPoints([]);
  }
  async function refreshCctv() {
    try {
      const r = await api("/api/v1/reference/cctv");
      map.setPoints(r.items.map(p => ({ lat: p.lat, lon: p.lon, label: `CCTV ${p.name ?? ""} ${CCTV_LABEL[p.wh_cd] ?? ""}` })));
    } catch (err) { map.setPoints([]); }
  }

  // ---------- 경로 ----------
  function renderRoute(r, title) {
    const box = $("route-result"); box.replaceChildren();
    box.append(node("div", { class: "group-title" }, title));
    const s = r.summary;
    box.append(node("p", { class: "note" }, `지나는 구간 ${s.segments}개 (${r.matched_km}km) · 경계·심각 ${s.high_grade_segments}개 · 결빙 가능 조건 ${s.condition_segments}개 · 모델 예측 ${s.prediction_segments}개` +
      (s.coldest ? ` · 최저 ${fmtT(s.coldest.rst_est)}(${s.coldest.seg_id})` : "")));
    const risky = r.segments.filter(x => x.state || GRADES.indexOf(x.grade) >= 2).slice(0, 12);
    if (risky.length) {
      const t = node("table"), hr = node("tr");
      ["구간", "통과", "등급", "노면", "상태"].forEach(c => hr.append(node("th", {}, c)));
      const head = node("thead"); head.append(hr); t.append(head);
      const tb = node("tbody");
      risky.forEach(x => {
        const tr = node("tr", { "data-seg": x.seg_id });
        tr.onclick = () => selectSegment(x.seg_id);
        [x.seg_id, r.mode === "history" ? (x.eta || "").slice(11, 16) : "-", x.grade, fmtT(x.rst_est), x.status.label].forEach(v => tr.append(node("td", {}, v)));
        tb.append(tr);
      });
      t.append(tb); box.append(t);
    }
    r.notes.slice(1).forEach(n => box.append(node("p", { class: "note" }, n)));
  }
  function routeParams() {
    return view.mode === "history" ? { mode: "history", at: view.at } : { mode: "live" };
  }
  function failRoute(err) { const box = $("route-result"); box.replaceChildren(node("p", { class: "error" }, err.message)); map.showRoute(null); }

  $("stretch-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const route = $("s-route").value, from_km = $("s-from").value, to_km = $("s-to").value;
    try {
      const r = await api(`/api/v1/route-risk/stretch?${new URLSearchParams({ route, from_km, to_km, ...routeParams() })}`);
      const coords = r.segments.flatMap(x => { const g = segById(x.seg_id).geometry; return g.type === "LineString" ? [g.coordinates] : g.coordinates; });
      map.showRoute(coords);
      renderRoute(r, `${route} ${from_km}~${to_km}km (시속 ${r.travel.speed_kmh}km 가정)`);
    } catch (err) { failRoute(err); }
  });
  $("naver-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    try {
      const r = await api(`/api/v1/naver/directions?${new URLSearchParams({ start: $("n-start").value, goal: $("n-goal").value, ...routeParams() })}`);
      map.showRoute([r.path]);
      renderRoute(r, `경로 ${(r.route.distance_m / 1000).toFixed(1)}km · ${(r.route.duration_s / 60).toFixed(0)}분 (네이버 Directions 5)`);
    } catch (err) { failRoute(err); }
  });
  $("open-route-app").onclick = () => {
    const [slng, slat] = $("n-start").value.split(",").map(Number), [dlng, dlat] = $("n-goal").value.split(",").map(Number);
    if ([slng, slat, dlng, dlat].some(Number.isNaN)) { showBanner("출발지와 도착지를 먼저 입력하세요."); return; }
    launchApp("route/car", { slat, slng, sname: "출발지", dlat, dlng, dname: "도착지" });
  };
  document.querySelectorAll("button[data-route-kind]").forEach(b => {
    b.onclick = () => {
      document.querySelectorAll("button[data-route-kind]").forEach(o => o.setAttribute("aria-pressed", String(o === b)));
      $("stretch-form").hidden = b.dataset.routeKind !== "stretch";
      $("naver-form").hidden = b.dataset.routeKind !== "naver";
    };
  });
  document.querySelectorAll("button[data-pick]").forEach(b => {
    b.onclick = () => {
      $("pick-hint").hidden = false;
      map.pick((lon, lat) => { $(b.dataset.pick).value = `${lon.toFixed(5)},${lat.toFixed(5)}`; $("pick-hint").hidden = true; });
    };
  });

  // ---------- 우선 구간 ----------
  let briefNo = 0;
  async function renderBriefing() {
    const no = ++briefNo, box = $("brief-result"), group = $("b-group").value, top = $("b-top").value;
    const date = view.mode === "history" && view.at ? view.at.slice(0, 10) : null;
    const q = view.mode === "live" ? { mode: "live", group, top } : { mode: "history", start: `${date}T18:00+09:00`, hours: 15, group, top };
    $("brief-window").textContent = view.mode === "live" ? "마지막 수신 시각의 상태 기준입니다. 앞으로의 예보가 아닙니다." : `${date} 18시부터 15시간의 과거 재생 자료 기준입니다.`;
    try {
      const r = await api(`/api/v1/ops/briefing?${new URLSearchParams(q)}`);
      if (no !== briefNo) return;
      box.replaceChildren();
      const groups = (r.groups || []).filter(g => g.alert_segments);
      if (!groups.length) { box.append(node("p", { class: "note" }, r.status ? r.status.label : "이 시간대에 결빙 가능 조건이나 모델 예측이 있는 구간이 없습니다. 안전 판정은 아닙니다.")); return; }
      groups.slice(0, 6).forEach(g => {
        box.append(node("div", { class: "group-title" }, `${g.group} · ${g.alert_segments}/${g.segments}구간`));
        const t = node("table"), head = node("thead"), hr = node("tr");
        [["구간"], ["등급"], ["조건h", 1], ["예측h", 1], ["최저", 1]].forEach(([c, n]) => hr.append(node("th", n ? { class: "num" } : {}, c)));
        head.append(hr); t.append(head);
        const tb = node("tbody");
        g.top.forEach(x => {
          const tr = node("tr", { "data-seg": x.seg_id }); tr.onclick = () => selectSegment(x.seg_id);
          tr.append(node("td", {}, x.seg_id), node("td", {}, x.grade), node("td", { class: "num" }, x.condition_hours), node("td", { class: "num" }, x.prediction_hours), node("td", { class: "num" }, fmtT(x.min_rst)));
          tb.append(tr);
        });
        t.append(tb); box.append(t);
      });
      if (groups.length > 6) box.append(node("p", { class: "note" }, `외 ${groups.length - 6}개 묶음은 API로 볼 수 있습니다.`));
      box.append(node("p", { class: "note" }, r.notes[0]));
    } catch (err) {
      if (no === briefNo) box.replaceChildren(node("p", { class: "error" }, err.message));
    }
  }
  $("b-group").onchange = renderBriefing;
  $("b-top").onchange = renderBriefing;

  // ---------- 조작 ----------
  function setAt() { view.at = `${$("date").value}T${$("hour").value}:00+09:00`; refresh(); }
  $("date").onchange = setAt;
  $("hour").onchange = setAt;
  $("event").onchange = ev => { if (ev.target.value) { $("date").value = ev.target.value; $("hour").value = "06"; setAt(); } };
  function setMode(mode) {
    view.mode = mode;
    document.querySelectorAll("button[data-mode]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.mode === mode)));
    $("time-box").hidden = mode !== "history";
    clearInterval(liveTimer); liveTimer = null;
    if (mode === "live") liveTimer = setInterval(refresh, 60000);
    refresh();
  }
  document.querySelectorAll("button[data-mode]").forEach(b => { b.onclick = () => setMode(b.dataset.mode); });
  document.querySelectorAll("button[data-color]").forEach(b => {
    b.onclick = () => {
      view.color = b.dataset.color;
      document.querySelectorAll("button[data-color]").forEach(o => o.setAttribute("aria-pressed", String(o === b)));
      repaint();
    };
  });

  // ---------- 시작 ----------
  let stationsMeta = [];
  try {
    const [m, seg, st, geo] = await Promise.all([api("/api/v1/metadata"), api("/api/v1/segments"), api("/api/v1/stations"), api("/assets/municipalities.geojson")]);
    meta = m; segments = seg.features; stationsMeta = st.stations;

    meta.routes.forEach(r => $("s-route").append(node("option", { value: r }, r)));
    const maxKm = () => Math.ceil(Math.max(...segments.filter(f => f.properties.route === $("s-route").value).map(f => f.properties.km_to)));
    $("s-route").onchange = () => { $("s-to").value = maxKm(); };
    $("s-to").value = maxKm();
    for (let h = 0; h < 24; h++) $("hour").append(node("option", { value: String(h).padStart(2, "0") }, `${String(h).padStart(2, "0")}시`));
    meta.event_days.forEach(e => $("event").append(node("option", { value: e.date }, `${e.date} · 예측 ${e.segments_predicted}구간`)));
    const first = [...meta.event_days].sort((a, b) => b.segments_predicted - a.segments_predicted)[0];
    $("date").min = meta.history.periods[0].start.slice(0, 10);
    $("date").max = meta.history.periods.at(-1).end.slice(0, 10);
    $("date").value = first ? first.date : $("date").min;
    $("hour").value = "06";
    view.at = `${$("date").value}T06:00+09:00`;

    $("naver-state").textContent = CONFIG.directions ? "네이버 Directions 5로 경로를 받아 우리 구간과 맞춥니다."
      : "서버에 Directions 키가 없어 이 조회는 쓸 수 없습니다. 노선 구간 조회는 키 없이 됩니다.";
    $("foot").textContent = `모델: ${meta.models.road_temperature.method}, 검증 지점 노면온도 MAE ${meta.performance.road_temperature.holdout.find(r => r.stn === "mean").MAE.toFixed(2)}°C. ${meta.notes[0]}`;

    const el = $("map");
    if (CONFIG.naverKeyId) {
      try {
        const maps = await loadNaverSdk(CONFIG.naverKeyId);
        map = new NaverMap(el, maps, segments, on);
        $("basemap-note").textContent = "배경 지도: NAVER Maps · 위험도 값: 이 서버의 API";
      } catch (err) {
        map = null;
        showBanner(`${err.message}. 내장 지도로 표시합니다.`);
      }
    }
    if (!map) {
      map = new SvgMap(el, segments, geo, on);
      if (!$("basemap-note").textContent) $("basemap-note").textContent = "배경 지도: 내장 시군 경계 (네이버 키 없음) · 위험도 값: 이 서버의 API";
    }
    // 네이버 인증 실패가 지도 생성 뒤에 오면 내장 지도로 바꾼다
    window.navermap_authFailure = () => {
      el.replaceChildren();
      map = new SvgMap(el, segments, geo, on);
      showBanner("네이버 지도 인증에 실패해 내장 지도로 표시합니다. Client ID와 Web 서비스 URL을 확인하세요.");
      repaint();
    };
    if (meta.vulnerable_sections) { const v = await api("/api/v1/ops/vulnerable"); map.setOverlay(v.geojson); }
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readColors(); repaint(); });
    setMode(new URLSearchParams(location.search).get("mode") === "live" ? "live" : "history");
  } catch (err) {
    $("summary-note").textContent = "서버 자료를 읽지 못했습니다: " + err.message;
    console.error(err);
  }
})();
