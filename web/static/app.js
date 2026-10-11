/* BTCUSDT 4 Saat — canlı teknik analiz arayüzü
 *
 * Grafik tarayıcıda ECharts ile çizilir. Bunun pratik sonucu:
 *   · mum/fiyat güncellemesi anlık; masaüstü matplotlib sürümündeki
 *     ~500 ms çizim süresinin yarattığı "donma" ortadan kalkar
 *   · crosshair + tooltip tarayıcının kendi canvas'ı sayesinde anlık
 *   · tekerlek yakınlaştırma, sürükleyerek kaydırma, sığdırma hazır geliyor
 *
 * ---------------------------------------------------------------------
 * Bu dosyanın yazılmasıyla ortaya çıkan ve burada not düşülmüş 5 tuzak:
 *
 * 1) ECharts'te HAZIR "star" sembolü YOKTUR. symbol:'star' yazınca
 *    sessizce kutuya düşer. Gerçek yıldız için image:// + base64 SVG
 *    kullaniliyor (STAR_URI).
 *
 * 2) setOption(opt, true) yani notMerge TUM option'i siler. Biz sadece
 *    xAxis+series gonderdigimiz icin grid/yAxis/dataZoom kayboluyor ve
 *    ECharts "Cannot read properties of undefined (reading
 *    'coordinateSystem')" hatasi veriyor. Her zaman MERGE kullanilir.
 *
 * 3) ECharts mum dizisi [acilis, kapanis, enDusuk, enYuksek] yani OCLH.
 *    Sunucudan gelen [zaman, acilis, enYuksek, enDusuk, kapanis, hacim].
 *
 * 4) setOption({series:[{data:[...]}]}) seri verisinin TAMAMINI
 *    degistirir. Sadece son mumu yenilemek icin data:[ohlc(c)] gondermek
 *    400 mumu tek muma dusuruyor ve grafik bos kaliyor. Tick'te dizinin
 *    tamami gonderilir.
 *
 * 5) setOption diziye GIRINTILI (sparse) seri listesi verilirse
 *    tanimsiz ogeler hataya yol acabilir; diziler her zaman dolu.
 * ---------------------------------------------------------------------
 */
// ---------------------------------------------------------------------
// PWA: "Ana ekrana ekle" icin service worker kaydi.
//
// DIKKAT: sw.js kendi kapsaminda degistirilirse hicbir sey degismez.
// Degisiklik yapildiginda VERSION'u arttir, aksi halde tarayici eski
// dosyayi kullanmayi devam eder ve kullanici guncel surumu gormez.
//
// skipWaiting() CAGRILMAZ: canli islem sirasinda sayfa yarida
// guncellenirse mum/gosterge durumu kaybolur. Yeni surum bir sonraki
// acilista devreye girer.
// ---------------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    // /sw.js (KOKTEN): /static/sw.js kovasi "/static/" olurdu ve ana
    // sayfayi denetleyemezdi; bkz. web/server.py::service_worker.
    navigator.serviceWorker.register("/sw.js")
      .catch(function (e) { console.warn("SW kaydedilemedi:", e); });
  });
}

(function () {
  "use strict";

  var IDX = {
    candle: 0, volume: 1, composite: 2,
    ema20: 3, ema50: 4, ema200: 5, sma200: 6, hma: 7, vwma: 8,
    buyStars: 9, sellStars: 10
  };
  var MA_ORDER = ["ema20", "ema50", "ema200", "sma200", "hma", "vwma"];
  var MA_DEF = [
    { key: "ema20", color: "#f7a35c", width: 1.2 },
    { key: "ema50", color: "#4fc3f7", width: 1.2 },
    { key: "ema200", color: "#b07cff", width: 1.4 },
    { key: "sma200", color: "#8d9db0", width: 1.1 },
    { key: "hma",   color: "#ff8fb1", width: 1.3 },
    { key: "vwma",  color: "#7dd6a0", width: 1.2 }
  ];

  /* --- GERÇEK YILDIZ: base64 SVG (ECharts'te hazir star sembolü yok) --- */
  function starUri(fill) {
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" ' +
      'viewBox="0 0 24 24">' +
      '<path d="M12 1.4 L15.4 8.3 L23 9.4 L17.5 14.7 L18.8 22.3 L12 18.7 ' +
      'L5.2 22.3 L6.5 14.7 L1 9.4 L8.6 8.3 Z" fill="' + fill + '" ' +
      'stroke="#080d14" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    return "image://data:image/svg+xml;base64," +
           btoa(unescape(encodeURIComponent(svg)));
  }
  var STAR_BUY  = starUri("#00c853");
  var STAR_SELL = starUri("#ff5252");

  var state = {
    candles: [], candleMap: {}, markers: [],
    symbol: "BTCUSDT", tf: "4h", signal: "NÖTR",
    strong: 0.65, base: 0.40,
    tickCount: 0, lastTickAt: 0, firstLoad: true,
    showMa: true, showStars: true, visibleBars: 150,
    timeframes: ["15m", "1h", "4h"], tfLabels: {},
    symbols: ["BTCUSDT"], paper: null,
    switching: false, userTouched: false
  };

  // ==================================================================
  // DOM
  // ==================================================================
  var el = {};
  ["coinSel", "tfLabel", "tfSel", "price", "signalBadge", "score", "clock",
   "thStrong", "thBase", "applyTh", "showMa", "showStars",
   "btnFit", "btnReset", "dbInfo", "chart", "oscTable", "maTable",
   "oscCounts", "maCounts", "log", "connState", "tickInfo", "btnClearLog",
   "paperState", "wBalance", "wEquity", "wProfit", "wUnreal", "wLev",
   "wFee", "wTrades", "wLastLong", "wPeak", "wPosBox", "wPosTitle", "wPosBody",
   "pBalance", "pLev", "pFrac", "pFee", "pLook", "pHold", "pConfirm",
   "pBacktest", "pRule", "pMode", "pStart", "pLive", "pStop", "pReset",
   "wTradeList", "btBox", "btRange", "btBody",
   "liveBox", "lProfit", "lTrades", "lFee", "lStart", "lStatus"
  ].forEach(function (id) { el[id] = document.getElementById(id); });

  // ==================================================================
  // Bicimlendirme
  // ==================================================================
  function fmt(n) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("tr-TR", { minimumFractionDigits: 2,
                                                maximumFractionDigits: 2 });
  }
  function fmtVol(n) {
    if (!n) return "—";
    return Number(n).toLocaleString("tr-TR", { maximumFractionDigits: 2 });
  }
  function fmtTime(t) {
    var d = new Date(t * 1000), p = function (x) { return (x < 10 ? "0" : "") + x; };
    return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear() +
           " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }
  function nowTs() {
    var d = new Date(), p = function (x) { return (x < 10 ? "0" : "") + x; };
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }

  // Sunucudan gelen mum: [zaman, acilis, enYuksek, enDusuk, kapanis, hacim]
  // ECharts mum dizisi:    [acilis, kapanis, enDusuk, enYuksek]   (OCLH!)
  function ohlc(c) { return [c[1], c[4], c[3], c[2]]; }
  function candleUp(c) { return c[4] >= c[1]; }        // kapanis >= acilis
  function volItem(c) {
    return { value: c[5],
             itemStyle: { color: candleUp(c) ? "#26a69a" : "#ef5350" } };
  }

  // Yaklastiginda tarih, yakinlastiginda tarih+saat gosterir.
  function fmtAxis(v) {
    var t = Number(v);
    if (!isFinite(t)) return "";
    var d = new Date(t * 1000), p = function (x) { return (x < 10 ? "0" : "") + x; };
    if (state.visibleBars > 90) {
      return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." +
             String(d.getFullYear()).slice(2);
    }
    return p(d.getDate()) + "." + p(d.getMonth() + 1) + "  " +
           p(d.getHours()) + ":" + p(d.getMinutes());
  }

  // ==================================================================
  // Grafik
  // ==================================================================
  var chart = echarts.init(el.chart, null, { renderer: "canvas" });
  chart.setOption(buildOption());

  function buildOption() {
    var maSeries = MA_DEF.map(function (m) {
      return {
        name: m.key, type: "line", data: [], showSymbol: false,
        smooth: false, connectNulls: true, silent: true,
        lineStyle: { width: m.width, color: m.color, opacity: 1 },
        itemStyle: { color: m.color, opacity: 1 },
        emphasis: { disabled: true }, z: 4
      };
    });

    return {
      backgroundColor: "transparent",
      animation: false,
      grid: [
        { left: 62, right: 86, top: 24, height: "60%" },
        { left: 62, right: 86, top: "73%", height: "17%" }
      ],
      axisPointer: {
        link: [{ xAxisIndex: "all" }],
        label: { backgroundColor: "#22303f", color: "#c9d6e4" }
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        backgroundColor: "#0a1017",
        borderColor: "#3d5570",
        padding: [8, 10],
        textStyle: { color: "#e8eef6", fontSize: 12 },
        formatter: tooltipFormatter
      },
      xAxis: [
        {
          type: "category", data: [], boundaryGap: true,
          axisLine: { lineStyle: { color: "#22303f" } },
          axisLabel: { color: "#6f8298", fontSize: 10, hideOverlap: true,
                       formatter: fmtAxis },
          splitLine: { show: false },
          axisPointer: { z: 100 }
        },
        {
          type: "category", gridIndex: 1, data: [],
          axisLine: { lineStyle: { color: "#22303f" } },
          axisLabel: { show: false }, splitLine: { show: false },
          axisPointer: { show: false }
        }
      ],
      yAxis: [
        {
          scale: true,
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: "#6f8298", fontSize: 10,
            formatter: function (v) { return v.toLocaleString("tr-TR"); } },
          splitLine: { lineStyle: { color: "#16202c" } }
        },
        { gridIndex: 1, scale: true, show: false },              // hacim
        { gridIndex: 1, min: -1, max: 1,                        // bilesik skor
          axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: "#8a7a3a", fontSize: 9, showMinLabel: false },
          splitLine: { lineStyle: { color: "#1c2530" } } }
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start: 62, end: 100 },
        {
          type: "slider", xAxisIndex: [0, 1], bottom: 2, height: 14,
          start: 62, end: 100, borderColor: "#22303f",
          backgroundColor: "#0f1826",
          fillerColor: "rgba(38,166,154,.14)",
          handleStyle: { color: "#4fc3f7" },
          textStyle: { color: "#6f8298", fontSize: 9 },
          dataBackground: { lineStyle: { color: "#22303f" },
                            areaStyle: { color: "#16202c" } },
          selectedDataBackground: { lineStyle: { color: "#4fc3f7" },
                                    areaStyle: { color: "#132030" } }
        }
      ],
      series: buildSeries().concat(maSeries).concat([
        {                                        // 9 · AL yildizlari
          id: "starsBuy", name: "AL", type: "scatter",
          symbol: STAR_BUY, z: 20, silent: true, tooltip: { show: false },
          symbolSize: function (v) { return (v && v[2]) ? 21 : 13; },
          data: []
        },
        {                                        // 10 · SAT yildizlari
          id: "starsSell", name: "SAT", type: "scatter",
          symbol: STAR_SELL, z: 20, silent: true, tooltip: { show: false },
          symbolSize: function (v) { return (v && v[2]) ? 21 : 13; },
          data: []
        }
      ])
    };
  }

  function buildSeries() {
    return [
      {                                        // 0 · mum
        name: "BTCUSDT", type: "candlestick", data: [],
        itemStyle: { color: "#26a69a", color0: "#ef5350",
                     borderColor: "#26a69a", borderColor0: "#ef5350" },
        // Sarı canlı fiyat çizgisi. markLine.data ilk anda BOŞ olmalı;
        // {yAxis: null} yazmak ECharts'i kırıyor.
        markLine: {
          symbol: "none", silent: true, animation: false, precision: 2,
          lineStyle: { color: "#ffd54f", width: 1, type: "dashed" },
          label: {
            show: true, position: "end", color: "#0a1017",
            backgroundColor: "#ffd54f", fontSize: 10, fontWeight: "bold",
            formatter: function (p) {
              return Number(p.value).toLocaleString("tr-TR",
                { minimumFractionDigits: 2 });
            }
          },
          data: []
        }
      },
      {                                        // 1 · hacim
        name: "Hacim", type: "bar", xAxisIndex: 1, yAxisIndex: 1,
        data: [], silent: true
      },
      {                                        // 2 · bilesik skor
        name: "Bileşik", type: "line", xAxisIndex: 1, yAxisIndex: 2,
        data: [], showSymbol: false, smooth: false, silent: true,
        lineStyle: { width: 1.6, color: "#ffd54f" },
        markLine: {
          symbol: "none", silent: true,
          lineStyle: { color: "#3d5570", width: 1, type: "dashed" },
          label: { show: false },
          data: [{ yAxis: state.base }, { yAxis: state.strong },
                 { yAxis: -state.base }, { yAxis: -state.strong }]
        }
      }
    ];
  }

  // ==================================================================
  // Tooltip
  // ==================================================================
  function tooltipFormatter(params) {
    if (!params || !params.length) return "";
    var c = state.candles[params[0].dataIndex];
    if (!c) return "";
    var sig = "";
    for (var i = 0; i < state.markers.length; i++) {
      if (state.markers[i].t === c[0]) sig = state.markers[i].signal;
    }
    var col = candleUp(c) ? "#26a69a" : "#ef5350";
    var arrow = candleUp(c) ? "▲" : "▼";
    var out = '<div style="color:' + col + ';font-weight:700">' +
              arrow + " " + fmt(c[4]) + "</div>" +
              '<div style="color:#9fb3c8">' + fmtTime(c[0]) + "</div>" +
              "Aç  " + fmt(c[1]) + "   Yük " + fmt(c[2]) + "<br>" +
              "Kapa " + fmt(c[4]) + "   Düşük " + fmt(c[3]) + "<br>" +
              "Hacim " + fmtVol(c[5]);
    if (sig && sig !== "NÖTR") {
      var sc = (sig === "AL" || sig === "GÜÇLÜ AL") ? "#00c853"
             : (sig === "SAT" || sig === "GÜÇLÜ SAT") ? "#ff5252"
             : "#8fa3b8";
      out += '<br><b style="color:' + sc + '">★ ' + sig + "</b>";
    }
    return out;
  }

  // ==================================================================
  // Veri
  // ==================================================================
  function applySnapshot(d) {
    // Dilim degistiyse grafik eski mumlarla karismasin: veriyi tamamen
    // temizleyip "Sığdır" gorunumunu yeni toplam mum sayisina gore kur.
    var yeniTf = d.timeframe || d.tf;
    if (yeniTf && yeniTf !== state.tf) {
      state.tf = yeniTf;
      state.firstLoad = true;
      state.candles = [];
      state.candleMap = {};
      state.markers = [];
      var patch = [];
      for (var i = 0; i <= 10; i++) {
        patch[i] = (i === IDX.candle || i === IDX.buyStars || i === IDX.sellStars)
          ? { data: [] }
          : { data: [] };
      }
      patch[IDX.candle].markLine = { data: [] };
      chart.setOption({ xAxis: [{ data: [] }, { data: [] }], series: patch });
    }

    state.symbol = d.symbol;
    state.strong = d.strong_threshold || state.strong;
    state.base = d.base_threshold || state.base;
    state.markers = d.markers || [];
    state.signal = d.signal;

    document.title = d.symbol + " · " + state.tf.toUpperCase() +
                     " Canlı Teknik Analiz";
    setBadge(d.signal);
    el.score.textContent = "bileşik " + d.composite_score.toFixed(3) +
      "  ·  osil. " + d.osc_score.toFixed(2) +
      "  ·  ort. " + d.ma_score.toFixed(2);

    state.candles = d.candles || [];
    state.candleMap = {};
    state.candles.forEach(function (c, i) { state.candleMap[c[0]] = i; });

    var times = state.candles.map(function (c) { return c[0]; });

    // Dizi her zaman DOLU (0..10) tutulur: setOption dizi bazinda
    // birlestirdigi icin delik birakilmamalidir.
    var series = [];
    series[IDX.candle]    = { data: state.candles.map(ohlc) };
    series[IDX.volume]    = { data: state.candles.map(volItem) };
    series[IDX.composite] = {
      data: d.composite || [],
      markLine: { data: [{ yAxis: state.base }, { yAxis: state.strong },
                         { yAxis: -state.base }, { yAxis: -state.strong }] }
    };
    MA_ORDER.forEach(function (k) {
      series[IDX[k]] = { data: (d.ma && d.ma[k]) || [] };
    });
    series[IDX.buyStars]  = { data: starData(true) };
    series[IDX.sellStars] = { data: starData(false) };

    chart.setOption({ xAxis: [{ data: times }, { data: times }],
                      series: series });          // MERGE (notMerge degil!)

    if (state.firstLoad) { state.firstLoad = false; fitView(); }

    renderTables(d.indicators, d.counts);
    setLivePrice(d.price);
  }

  // Sinyal yildizlari -> scatter verisi.
  // Kategori ekseni olduğu icin x = KATEGORI INDEKSI (zaman degil).
  // deger: [indeks, fiyat, gucluMu?1:0]
  function starData(buy) {
    if (!state.showStars) return [];
    var out = [];
    state.markers.forEach(function (m) {
      var isBuy = (m.signal === "AL" || m.signal === "GÜÇLÜ AL");
      if (isBuy !== buy) return;
      var idx = state.candleMap[m.t];
      if (idx === undefined || m.price === null) return;
      out.push({
        value: [idx, m.price, m.strong ? 1 : 0],
        // AL yildizi mumun ustunde, SAT altinda dursun
        symbolOffset: [0, buy ? -14 : 16],
        name: m.signal
      });
    });
    return out;
  }

  function setBadge(sig) {
    el.signalBadge.textContent = sig;
    el.signalBadge.className = "badge " +
      (sig === "GÜÇLÜ AL" ? "gal" : sig === "AL" ? "al" :
       sig === "SAT" ? "sat" : sig === "GÜÇLÜ SAT" ? "gsat" : "notr");
  }

  // --- ANLIK TİK ------------------------------------------------------
  // Her islemde (~4,5 msg/sn) mumun son hali ve sarı fiyat çizgisi
  // tazelenir. Dizi tamami gonderilir; bkz. dosya başındaki 4. madde.
  function applyTick(d) {
    // Sunucu uc dilimin de tiklerini uretir; yalnizca baktigimiz dilimi
    // uygula (yoksa 15m mumu 4h grafigine yazilir).
    if (d.tf && d.tf !== state.tf) return;

    state.tickCount++;
    var i = state.candleMap[d.t];
    if (i === undefined) return;          // yeni bar → sonraki snapshot'ta

    var c = state.candles[i];
    c[4] = d.price;                       // kapanis
    if (typeof d.high === "number" && d.high > c[2]) c[2] = d.high;
    if (typeof d.low === "number" && d.low < c[3]) c[3] = d.low;
    if (typeof d.volume === "number") c[5] = d.volume;

    var patch = [];
    patch[IDX.candle] = { data: state.candles.map(ohlc),
                          markLine: { data: [{ yAxis: d.price }] } };
    patch[IDX.volume] = { data: state.candles.map(volItem) };
    chart.setOption({ series: patch }, { lazyUpdate: true });

    el.price.textContent = fmt(d.price);
    state.lastTickAt = Date.now();
  }

  function setLivePrice(p) {
    if (p === null || p === undefined) return;
    el.price.textContent = fmt(p);
    var patch = [];
    patch[IDX.candle] = { markLine: { data: [{ yAxis: p }] } };
    chart.setOption({ series: patch }, { lazyUpdate: true });
  }

  // ==================================================================
  // Tablolar
  // ==================================================================
  function renderTables(ind, counts) {
    fill(el.oscTable, ind ? ind.osc : []);
    fill(el.maTable, ind ? ind.ma : []);
    if (counts) {
      el.oscCounts.textContent = "Al " + counts.osc.buy + " · Sat " +
        counts.osc.sell + " · Nötr " + counts.osc.neutral;
      el.maCounts.textContent = "Al " + counts.ma.buy + " · Sat " +
        counts.ma.sell + " · Nötr " + counts.ma.neutral;
    }
  }

  function fill(node, rows) {
    var html = "";
    (rows || []).forEach(function (r) {
      var cls = r.v === 1 ? "d-buy" : (r.v === -1 ? "d-sell" : "d-neutral");
      html += '<div class="row"><span>' + r.ad + "</span>" +
              '<span class="v">' + r.deger + "</span>" +
              '<span class="' + cls + '">' + r.vad + "</span></div>";
    });
    node.innerHTML = html;
  }

  // ==================================================================
  // Log
  // ==================================================================
  function pushLog(div) {
    el.log.appendChild(div);
    while (el.log.childElementCount > 400) el.log.removeChild(el.log.firstChild);
    el.log.scrollTop = el.log.scrollHeight;
  }

  function addLog(ts, level, text) {
    var d = document.createElement("div");
    d.innerHTML = '<span class="ts">' + ts + '</span> <span class="' +
                  (level || "info") + '">' + text + "</span>";
    pushLog(d);
  }

  function addSignalLog(ts, signal, text) {
    var col = (signal === "AL" || signal === "GÜÇLÜ AL") ? "#00c853"
            : (signal === "SAT" || signal === "GÜÇLÜ SAT") ? "#ff5252"
            : "#8fa3b8";
    var d = document.createElement("div");
    d.innerHTML = '<span class="ts">' + ts + '</span> <span class="star" style="color:' +
                  col + '">★ ' + signal + "</span> " + text;
    pushLog(d);
  }

  // ==================================================================
  // WebSocket
  // ==================================================================
  var ws = null, retry = 0;

  function connect() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(proto + "//" + location.host + "/ws");

    ws.onopen = function () {
      retry = 0;
      el.connState.textContent = "bağlı";
      el.connState.className = "conn ok";
    };
    ws.onclose = function () {
      el.connState.textContent = "bağlantı kesildi — yeniden deneniyor…";
      el.connState.className = "conn bad";
      retry = Math.min(retry + 1, 6);
      setTimeout(connect, 500 * retry);
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} };
    ws.onmessage = function (ev) {
      var d;
      try { d = JSON.parse(ev.data); } catch (e) { return; }

      switch (d.type) {
        case "hello":
          if (d.timeframes) state.timeframes = d.timeframes;
          state.tfLabels = d.tf_labels || {};
          if (d.symbols) state.symbols = d.symbols;
          if (d.symbol) state.symbol = d.symbol;
          renderCoins(state.symbols, state.symbol);
          renderTimeframeButtons(d.timeframe);
          updateTfLabel();
          if (d.db_signals !== undefined) {
            el.dbInfo.textContent = d.db_signals + " sinyal · " +
              d.db_logs + " log · " + d.db_kb + " KB";
          }
          break;

        case "timeframe_ack":
          state.switching = false;
          renderTimeframeButtons(d.timeframe);
          updateTfLabel();
          break;

        case "wallet":
          applyWallet(d);
          break;

        case "symbol_changed":
          onSymbolChanged(d.symbol);
          break;

        case "snapshot": applySnapshot(d); break;
        case "tick":     applyTick(d); break;
        case "log":      addLog(d.ts, d.level, d.text); break;
        case "signal_log": addSignalLog(d.ts, d.signal, d.text); break;
      }
    };
  }

  // ==================================================================
  // Zaman dilimi secimi
  // ==================================================================
  function tfLabel(tf) {
    return state.tfLabels[tf] || tf;
  }

  // Buton metni kisa olmali: "15dk / 1sa / 4sa" yerine uzun etiket
  // basligi sIKISTIRIR.
  function kisaEtiket(tf) {
    return ({ "15m": "15dk", "1h": "1sa", "2h": "2sa", "4h": "4sa",
              "1d": "1gün" })[tf] || tf;
  }

  function updateTfLabel() {
    el.tfLabel.textContent = tfLabel(state.tf) + " · " + state.tf;
  }

  function renderTimeframeButtons(aktif) {
    var btns = el.tfSel.querySelectorAll(".tfbtn");
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      var tf = b.getAttribute("data-tf");
      b.classList.toggle("aktif", tf === aktif);
      b.classList.toggle("bekliyor", state.switching && tf === aktif);
    }
  }

  function selectTimeframe(tf) {
    if (!tf || tf === state.tf || state.switching) return;
    if (state.timeframes.indexOf(tf) < 0) return;
    state.switching = true;
    // Grafiği hemen bosalt: yeni mumlar gelene kadar eski dilimin
    // mumlari ekranda kalip yanlis bilgi vermesin.
    state.candles = [];
    state.candleMap = {};
    state.markers = [];
    state.firstLoad = true;
    var patch = [];
    for (var i = 0; i <= 10; i++) patch[i] = { data: [] };
    patch[IDX.candle].markLine = { data: [] };
    chart.setOption({ xAxis: [{ data: [] }, { data: [] }], series: patch });
    el.price.textContent = "—";
    el.score.textContent = "yükleniyor…";
    el.oscCounts.textContent = "";
    el.maCounts.textContent = "";

    renderTimeframeButtons(tf);
    updateTfLabel();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "set_timeframe", tf: tf }));
    }
    // Guvenlik agi: sunucudan yanit gelmezse butonler kilitli kalmasin.
    setTimeout(function () { state.switching = false; renderTimeframeButtons(state.tf); }, 8000);
  }

  el.tfSel.addEventListener("click", function (ev) {
    var b = ev.target.closest(".tfbtn");
    if (b) selectTimeframe(b.getAttribute("data-tf"));
  });

  // ==================================================================
  // Sanal cüzdan / kaldıraç simülatörü
  // ==================================================================
  function fmtUsd(n) {
    if (n === null || n === undefined) return "—";
    return Number(n).toLocaleString("tr-TR", { minimumFractionDigits: 2,
                                                maximumFractionDigits: 2 });
  }
  function signed(n) {
    if (n === null || n === undefined) return "—";
    var v = Number(n);
    return (v > 0 ? "+" : "") + fmtUsd(v);
  }
  function cls(n) {
    if (n === null || n === undefined) return "";
    return Number(n) > 0 ? " pos" : (Number(n) < 0 ? " neg" : "");
  }

  function applyWallet(d) {
    state.paper = d;
    el.paperState.textContent = d.running ? "çalışıyor" : "durduruldu";
    el.paperState.className = "counts " + (d.running ? "on" : "off");

    // Ayarlari sunucudan gelen degerlerle hizala. DIKKAT: saniyede bir
    // gelen cuzdan mesaji, kullaniciyi listeden secim yaparken geri
    // ezmemeli. Kullanici bir ayara dokunduysa bir daha dokunmuyoruz.
    if (!state.userTouched) {
      if (document.activeElement !== el.pConfirm) {
        el.pConfirm.checked = !!d.confirm;
      }
      if (document.activeElement !== el.pLook) el.pLook.value = d.lookback;
      if (document.activeElement !== el.pHold) el.pHold.value = d.min_hold_bars;
      if (document.activeElement !== el.pRule) el.pRule.value = d.short_rule;
      if (document.activeElement !== el.pMode) el.pMode.value = d.mode;
    }

    el.wBalance.textContent = fmtUsd(d.balance);
    el.wEquity.textContent = fmtUsd(d.equity);
    el.wProfit.textContent = signed(d.profit) + "  (" +
      (d.profit >= 0 ? "+" : "") +
      (d.start_balance ? (d.profit / d.start_balance * 100).toFixed(2) : "0") +
      "%)";
    el.wProfit.className = "wv" + cls(d.profit);
    el.wUnreal.textContent = d.position ? signed(d.unrealized) : "—";
    el.wUnreal.className = "wv" + cls(d.unrealized);
    el.wLev.textContent = d.leverage + "x  (teminat %" +
      Math.round(d.wallet_fraction * 100) + ")";
    el.wFee.textContent = fmtUsd(d.totals.commission) + "  (%" +
      (d.fee_rate * 100).toFixed(3) + " işlem başına)";

    var t = d.totals;
    el.wTrades.textContent = t.trades + "  (" + t.wins + " kazanç / " +
      t.losses + " kayıp)";
    el.wLastLong.textContent = d.last_long_price !== null &&
      d.last_long_price !== undefined ? fmt(d.last_long_price) : "—";

    // Zirve referansı (SHORT kuralı = tepeden geri çekilme)
    el.wPeak.textContent = d.long_peak ? fmt(d.long_peak) : "—";

    // Açık pozisyon
    var box = el.wPosBox;
    if (d.position) {
      var p = d.position;
      box.className = "posbox " + (p.side === "LONG" ? "long" : "short");
      el.wPosTitle.textContent = p.side + " AÇIK";
      el.wPosBody.innerHTML =
        "Giriş   <b>" + fmt(p.entry) + "</b><br>" +
        "Miktar  " + p.qty.toLocaleString("tr-TR",
          { maximumFractionDigits: 6 }) + "<br>" +
        "Teminat " + fmtUsd(p.margin) + "  ·  " +
        "poz. " + fmtUsd(p.notional) + "<br>" +
        "Kâr/zarar <b>" + signed(p.unrealized) + "</b><br>" +
        "Hedef <b style='color:#4ade80'>" + fmt(p.target) + "</b><br>" +
        "Likidasyon <b style='color:#ffb300'>" + fmt(p.liq_price) + "</b><br>" +
        "Pencere " + fmt(p.window_low) + " – " + fmt(p.window_high) + "<br>" +
        "<span style='color:#6f8298'>" + p.reason + "</span>";
    } else {
      box.className = "posbox none";
      el.wPosTitle.textContent = "Pozisyon yok";
      el.wPosBody.innerHTML =
        "<span style='color:#6f8298'>LONG: fiyat pencerenin tabanında.<br>" +
        "SHORT: zirvede, ama son LONG fiyatının altında.</span>";
    }

    // Geçmiş test özeti: "bugüne kadar ne kazandı?"
    var bt = d.backtest;
    if (bt && !bt.error) {
      el.btBox.className = "btbox";
      var f1 = new Date(bt.from).toLocaleDateString("tr-TR");
      var f2 = new Date(bt.to).toLocaleDateString("tr-TR");
      el.btRange.textContent = f1 + " → " + f2 + " · " + bt.bars + " " +
        bt.timeframe + " mum · " + bt.elapsed_ms + " ms";
      el.btBody.innerHTML =
        '<div class="btrow"><span>İşlem</span><b>' + bt.trades +
        "</b> (" + bt.wins + " kazanç / " + bt.losses + " kayıp)</div>" +
        '<div class="btrow"><span>Brüt</span><b class="' +
        (bt.gross_pnl >= 0 ? "pos" : "neg") + '">' + signed(bt.gross_pnl) +
        "</b></div>" +
        '<div class="btrow"><span>Komisyon</span><b class="neg">' +
        signed(-bt.commission) + "</b></div>" +
        '<div class="btrow"><span>Bugünkü bakiye</span><b>' +
        fmtUsd(bt.balance) + "</b></div>" +
        '<div class="btrow big"><span>Net kâr</span><b class="' +
        (bt.profit >= 0 ? "pos" : "neg") + '">' + signed(bt.profit) +
        "  (" + (bt.return_pct >= 0 ? "+" : "") + bt.return_pct +
        "%)</b></div>" +
        (bt.open_position
          ? '<div class="btrow"><span>Açık pozisyon</span><b>' +
            bt.open_position + " (test sonunda açık kaldı)</b></div>"
          : "");
    } else {
      el.btBox.className = "btbox none";
      el.btRange.textContent = "";
      el.btBody.innerHTML = "";
    }

    // ---- CANLI ISLEM paneli -------------------------------------------
    // Kullanicinin asil sordugu sey: "Trade Basla" dedikten sonraki
    // gercek kâr/zarar. Gecmis test sonuclari BURAYA karismaz.
    var lv = d.live || {};
    el.lProfit.textContent = lv.trades ? signed(lv.net_pnl) : "—";
    el.lProfit.className = "lv big" + cls(lv.net_pnl);
    el.lTrades.textContent = lv.trades
      ? lv.trades + "  (" + lv.wins + " kazanç / " + lv.losses + " kayıp)"
      : "—";
    el.lFee.textContent = lv.trades ? fmtUsd(lv.commission) : "—";
    el.lStart.textContent = lv.started_at
      ? new Date(lv.started_at * 1000).toLocaleTimeString("tr-TR")
      : "—";

    var bekliyor = d.running && d.position
      ? "pozisyon açık · " + d.position.side
      : (d.running ? "sinyal bekleniyor…" : "canlı işlem kapalı");
    el.lStatus.textContent = bekliyor;
    el.lStatus.className = "lstat" + (d.running ? " on" : "");
    el.liveBox.className = "livebox" + (d.running ? " on" : "");

    // İşlem geçmişi
    if (!d.trades || !d.trades.length) {
      el.wTradeList.innerHTML = '<div class="trades-empty">Henüz işlem yok</div>';
    } else {
      var html = "";
      d.trades.forEach(function (x) {
        html += '<div class="trades-row' +
          (x.mode === "backtest" ? " past" : "") + '">' +
          '<span class="' + (x.side === "LONG" ? "side-long" : "side-short") +
          '">' + x.side + (x.mode === "backtest" ? "·g" : "·c") + "</span>" +
          '<span class="num">' + fmt(x.entry) + "</span>" +
          '<span class="num">' + fmt(x.exit) + "</span>" +
          '<span class="num' + cls(x.pnl) + '">' + signed(x.pnl) + "</span>" +
          '<span class="num" style="color:#8a7a3a">' +
          x.commission.toFixed(4) + "</span></div>";
      });
      el.wTradeList.innerHTML = html;
    }
  }

  function paperConfig() {
    return {
      balance: parseFloat(el.pBalance.value),
      leverage: parseFloat(el.pLev.value),
      wallet_fraction: parseFloat(el.pFrac.value) / 100,
      fee_rate: parseFloat(el.pFee.value) / 100,
      lookback: parseInt(el.pLook.value, 10),
      min_hold: parseInt(el.pHold.value, 10) || 0,
      confirm: el.pConfirm.checked,
      backtest: el.pBacktest.checked,
      short_rule: el.pRule.value,
      mode: el.pMode.value,
      // Dilimi sunucuya ACIKCA bildir: sunucudaki aktif dilim WS mesajiyla
      // guncelleniyor ve iki istek araya girince yanlis dilim test edilebiliyor.
      timeframe: state.tf
    };
  }

  function paperCall(path) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(paperConfig())
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.state) applyWallet(d.state);
        if (!d.ok) {
          addLog(nowTs(), "error", d.error || "İşlem başarısız");
        }
        return d;
      });
  }

  // Kullanici bir ayara dokunduysa sunucudan gelen periyodik cuzdan
  // mesaji o alani EZMEMELI (saniyede bir geldigi icin secim kaybolurdu).
  ["pConfirm", "pBacktest", "pRule", "pMode"].forEach(function (id) {
    el[id].addEventListener("change", function () { state.userTouched = true; });
  });
  ["pBalance", "pLev", "pFrac", "pFee", "pLook", "pHold"].forEach(function (id) {
    el[id].addEventListener("input", function () { state.userTouched = true; });
  });

  // "Trade Basla": gecmis test OYNATILMAZ. Cuzdan verilen USDT ile
  // sifirlanir ve yalnizca o andan sonraki hareketler sayilir. Kullanicinin
  // sordugu tam olarak bu: "simdi basliyorum, canli kar/zarari izleyecegim".
  el.pLive.addEventListener("click", function () {
    var cfg = paperConfig();
    cfg.backtest = false;
    addLog(nowTs(), "info",
      "CANLI İŞLEM BAŞLATILIYOR · " + fmtUsd(cfg.balance) + " USDT · " +
      cfg.leverage + "x · " + (cfg.mode) + " modu");
    fetch("/api/paper/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cfg)
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.state) applyWallet(d.state);
        if (!d.ok) addLog(nowTs(), "error", d.error || "Başlatılamadı");
      });
  });

  el.pStart.addEventListener("click", function () {
    addLog(nowTs(), "info", "Geriye dönük test oynatılıyor, sonra canlı…");
    paperCall("/api/paper/start");
  });
  el.pStop.addEventListener("click", function () { paperCall("/api/paper/stop"); });
  el.pReset.addEventListener("click", function () {
    if (!confirm("Simülatör sıfırlansın mı?\n" +
                 "Cüzdan, açık pozisyon ve işlem geçmişi silinir.")) return;
    paperCall("/api/paper/reset");
  });

  // ==================================================================
  // Coin (sembol) seçimi
  // ==================================================================
  function renderCoins(symbols, aktif) {
    el.coinSel.innerHTML = (symbols || []).map(function (s) {
      return '<option value="' + s + '"' + (s === aktif ? " selected" : "") +
             ">" + s.replace("USDT", "/USDT") + "</option>";
    }).join("");
  }

  el.coinSel.addEventListener("change", function () {
    var sym = el.coinSel.value;
    if (sym === state.symbol) return;
    el.coinSel.disabled = true;
    state.switching = true;
    addLog(nowTs(), "warning", sym + " yükleniyor…");
    fetch("/api/symbol", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym })
    }).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          addLog(nowTs(), "error", d.error || "Sembol değiştirilemedi");
          renderCoins(state.symbols, state.symbol);
        }
      })
      .catch(function () { renderCoins(state.symbols, state.symbol); })
      .finally(function () {
        el.coinSel.disabled = false;
        state.switching = false;
      });
  });

  function onSymbolChanged(sym) {
    state.symbol = sym;
    // Grafik verisi tamamen degisecek: temizle
    state.candles = [];
    state.candleMap = {};
    state.markers = [];
    state.firstLoad = true;
    var patch = [];
    for (var i = 0; i <= 10; i++) patch[i] = { data: [] };
    patch[IDX.candle].markLine = { data: [] };
    chart.setOption({ xAxis: [{ data: [] }, { data: [] }], series: patch });
    el.price.textContent = "—";
    el.score.textContent = "yükleniyor…";
    el.oscTable.innerHTML = "";
    el.maTable.innerHTML = "";
    el.oscCounts.textContent = "";
    el.maCounts.textContent = "";
    renderCoins(state.symbols, sym);
    service_refresh();
  }

  function service_refresh() {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "refresh" }));
    }
  }
  function fitView() {
    var total = state.candles.length || 1;
    var start = Math.max(0, 100 - (150 / total) * 100);
    chart.dispatchAction({ type: "dataZoom", start: start, end: 100 });
  }

  // Zoom seviyesine gore eksen etiketi bicimi degissin (gun / saat)
  chart.on("dataZoom", function () {
    var dz = chart.getOption().dataZoom[0];
    var total = state.candles.length || 1;
    state.visibleBars = Math.round(((dz.end - dz.start) / 100) * total);
  });

  el.applyTh.addEventListener("click", function () {
    var s = parseFloat(el.thStrong.value), b = parseFloat(el.thBase.value);
    /* DIKKAT: JS'te "0 < b < 1" yazmak YANLISTIR. Zincirleme karsilastirma
     * olmadigi icin (0 < b) < 1 olarak hesaplanir; dogru sonuc true iken
     * "1 < 1" -> false olur ve her deger reddedilirdi. Python'da ayni
     * yazim dogru calisir, bu yuzden sunucu tarafi sorunsuzdu.
     * Karsilastirmalar && ile ayri ayri yazilir. */
    if (!(b > 0 && b < 1) || !(s >= b && s <= 1)) {
      addLog(nowTs(), "error",
             "Eşik geçersiz: 0 < AL/SAT ≤ GÜÇLÜ ≤ 1 olmalı");
      return;
    }
    state.strong = s; state.base = b;
    ws.send(JSON.stringify({ type: "set_thresholds", strong: s, base: b }));
    addLog(nowTs(), "ok", "Eşikler güncellendi: GÜÇLÜ ±" + s.toFixed(2) +
        ", AL/SAT ±" + b.toFixed(2));
  });

  el.btnFit.addEventListener("click", fitView);

  el.showMa.addEventListener("change", function () {
    state.showMa = el.showMa.checked;
    var op = state.showMa ? 1 : 0;
    var patch = [];
    MA_ORDER.forEach(function (k) {
      patch[IDX[k]] = { lineStyle: { opacity: op }, itemStyle: { opacity: op } };
    });
    chart.setOption({ series: patch }, { lazyUpdate: true });
  });

  el.showStars.addEventListener("change", function () {
    state.showStars = el.showStars.checked;
    var patch = [];
    patch[IDX.buyStars]  = { data: starData(true) };
    patch[IDX.sellStars] = { data: starData(false) };
    chart.setOption({ series: patch }, { lazyUpdate: true });
  });

  el.btnReset.addEventListener("click", function () {
    if (!confirm("Tüm sinyal kayıtları ve log satırları silinecek.\n" +
                 "Bu işlem geri alınamaz. Devam edilsin mi?")) return;
    fetch("/api/reset-db", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var n = 0;
        if (d.removed) {
          Object.keys(d.removed).forEach(function (k) { n += d.removed[k]; });
        }
        el.dbInfo.textContent = "0 sinyal · 0 log";
        addLog(nowTs(), "warning",
               "Veritabanı sıfırlandı — " + n + " kayıt silindi");
      });
  });

  el.btnClearLog.addEventListener("click", function () { el.log.innerHTML = ""; });

  window.addEventListener("resize", function () { chart.resize(); });

  setInterval(function () {
    el.clock.textContent = nowTs();
    if (state.lastTickAt) {
      var age = ((Date.now() - state.lastTickAt) / 1000).toFixed(1);
      el.tickInfo.textContent = "anlık tik: " + state.tickCount +
        "  ·  son tik " + age + " sn önce";
    }
  }, 1000);

  fetch("/api/state").then(function (r) { return r.json(); }).then(function (d) {
    state.symbol = d.symbol;
    if (d.symbols) state.symbols = d.symbols;
    renderCoins(state.symbols, state.symbol);
    el.thStrong.value = d.thresholds.strong;
    el.thBase.value = d.thresholds.base;
    if (d.timeframes && d.timeframes.length) {
      state.timeframes = d.timeframes;
      state.tfLabels = d.tf_labels || {};
      el.tfSel.innerHTML = d.timeframes.map(function (tf) {
        return '<button class="tfbtn" data-tf="' + tf + '">' +
               kisaEtiket(tf) + "</button>";
      }).join("");
    }
    renderTimeframeButtons(d.timeframe);
  }).catch(function () {});

  connect();
})();