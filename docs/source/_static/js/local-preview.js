// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

(() => {
  const localHosts = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
  if (!localHosts.has(window.location.hostname)) {
    return;
  }

  const currentScript = document.currentScript;
  if (currentScript && typeof DOCUMENTATION_OPTIONS !== "undefined") {
    DOCUMENTATION_OPTIONS.theme_switcher_json_url = new URL(
      "../../versions-local.json",
      currentScript.src,
    ).href;
  }

  const rejectOptionalCookies = () => {
    const rejectButton = document.getElementById("onetrust-reject-all-handler");
    if (!rejectButton) {
      return false;
    }

    rejectButton.click();
    return true;
  };

  if (!rejectOptionalCookies()) {
    const observer = new MutationObserver(() => {
      if (rejectOptionalCookies()) {
        observer.disconnect();
      }
    });
    observer.observe(document.documentElement, {childList: true, subtree: true});
    window.setTimeout(() => observer.disconnect(), 10000);
  }
})();
