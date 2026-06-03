// FridgeMate Cart Helper - content script (localhost:3000 페이지에 주입)
//
// FridgeMate 웹페이지 ↔ 익스텐션 background 사이의 다리(bridge).
// 페이지는 window.postMessage 로만 통신하므로 chrome.* 를 직접 알 필요가 없다.

// 1) 익스텐션 설치/활성 알림 (페이지가 버튼 활성화 여부 판단에 사용).
function announce() {
  window.postMessage({ type: "FRIDGEMATE_EXT_READY" }, "*");
}
announce();

// 확장 컨텍스트가 살아있는지 확인(확장 새로고침 후 orphan content script 방지).
function extensionAlive() {
  try {
    return Boolean(chrome.runtime && chrome.runtime.id);
  } catch (e) {
    return false;
  }
}

// 2) 페이지 → background
window.addEventListener("message", (e) => {
  if (e.source !== window || !e.data) return;
  const d = e.data;
  if (d.type === "FRIDGEMATE_PING") {
    announce();
  } else if (d.type === "FRIDGEMATE_EXEC_CART") {
    if (!extensionAlive()) {
      // 확장이 업데이트/새로고침되어 이 페이지의 스크립트가 끊긴 경우.
      window.postMessage(
        {
          type: "FRIDGEMATE_EXEC_RESULT",
          reqId: d.reqId,
          response: {
            executionMode: "extension",
            status: "failed",
            results: [],
            message:
              "확장 프로그램이 업데이트되어 연결이 끊겼어요. 이 페이지를 새로고침한 뒤 다시 시도해 주세요.",
          },
        },
        "*"
      );
      return;
    }
    try {
      chrome.runtime.sendMessage({
        type: "FRIDGEMATE_EXEC_CART",
        items: d.items || [],
        reqId: d.reqId,
      });
    } catch (err) {
      window.postMessage(
        {
          type: "FRIDGEMATE_EXEC_RESULT",
          reqId: d.reqId,
          response: {
            executionMode: "extension",
            status: "failed",
            results: [],
            message:
              "확장 연결이 끊겼어요. 이 페이지를 새로고침한 뒤 다시 시도해 주세요.",
          },
        },
        "*"
      );
    }
  }
});

// 3) background → 페이지 (진행률 + 실행 결과 중계)
chrome.runtime.onMessage.addListener((msg) => {
  if (
    msg &&
    (msg.type === "FRIDGEMATE_EXEC_RESULT" || msg.type === "FRIDGEMATE_EXEC_PROGRESS")
  ) {
    window.postMessage(msg, "*"); // reqId 포함 그대로 전달
  }
});
