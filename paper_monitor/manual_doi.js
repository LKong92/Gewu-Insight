/* Only the manual DOI save response opens this review. Nothing runs on load. */
(() => {
  window.reviewManualDoiConflict = review => new Promise(resolve => {
    const focus = document.activeElement;
    const backdrop = document.createElement("div");
    backdrop.className = "settings-backdrop open";
    backdrop.innerHTML = `<style>
      .doi-review {width:min(730px,calc(100vw - 44px))!important}
      .doi-review .settings-modal-body {font-size:12px;line-height:1.45;overflow:auto}
      .doi-review .doi-records {display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}
      .doi-review .doi-record {background:#fff;border:1px solid #dddde1;border-radius:9px;padding:13px;min-width:0}
      .doi-review .doi-record h3 {margin:6px 0;font-size:12px;line-height:1.4;overflow-wrap:anywhere}
      .doi-review .doi-label {font-size:11px;font-weight:650;color:#6e6e73}
      .doi-review .doi-record p {font-size:11px;margin:5px 0;overflow-wrap:anywhere;color:#6e6e73}
      .doi-review .doi-record .doi-key {font-family:ui-monospace,monospace;font-size:10px}
      .doi-review .doi-value {margin:0 0 12px;overflow-wrap:anywhere;font-size:12px}
      .doi-review .doi-options {margin-top:12px;background:#fff;border-radius:9px;overflow:hidden}
      .doi-review .doi-option {display:grid;grid-template-columns:16px minmax(0,1fr);gap:9px;padding:12px;cursor:pointer}
      .doi-review .doi-option + .doi-option {border-top:1px solid #dddde1}
      .doi-review .doi-option input {margin:3px 0 0;width:14px;height:14px}
      .doi-review .doi-option strong {display:block;font-size:12px}
      .doi-review .doi-option span {display:block;font-size:11px;color:#6e6e73;margin-top:3px}
      .doi-review .doi-actions {display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
      .doi-review .doi-actions button {width:180px;max-width:100%;height:30px;justify-content:center}
      .doi-review .doi-status {font-size:11px;color:#b42318;overflow-wrap:anywhere;margin-top:10px}
      .doi-review .doi-status:empty {display:none}
      @media(max-width:540px){.doi-review .doi-records{grid-template-columns:1fr}.doi-review .doi-actions{flex-wrap:wrap}}
    </style>
    <section class="settings-modal preferences-modal doi-review" role="dialog" aria-modal="true" aria-labelledby="doiReviewTitle" tabindex="-1">
      <div class="settings-modal-head"><div><h2 id="doiReviewTitle">Review DOI Conflict</h2><p>Compare these records before changing the DOI.</p></div>
        <button class="settings-modal-close" type="button" aria-label="Cancel">×</button></div>
      <div class="settings-modal-body">
        <p class="doi-value">DOI: <strong data-doi></strong></p>
        <div class="doi-records"><article class="doi-record" data-record="current"></article><article class="doi-record" data-record="existing"></article></div>
        <div class="doi-options">
          <label class="doi-option"><input type="radio" name="doi-resolution" value="merge"><div><strong>These are the same paper</strong><span data-merge-description></span></div></label>
          <label class="doi-option"><input type="radio" name="doi-resolution" value="reassign"><div><strong>These are different papers</strong><span>Remove the incorrect DOI from the existing record and assign it to the current paper. Keep both Gewu Keys, files and Monitor entries separate.</span></div></label>
        </div>
        <div class="doi-status" role="status" aria-live="polite"></div>
        <div class="doi-actions"><button class="smallbtn" type="button" data-cancel>Cancel</button><button class="smallbtn primary" type="button" data-confirm disabled>Choose an Option</button></div>
      </div>
    </section>`;
    const node = selector => backdrop.querySelector(selector);
    const line = (parent, tag, text, cls = "") => {
      const el = document.createElement(tag); el.textContent = text; el.className = cls; parent.append(el);
    };
    node("[data-doi]").textContent = review.doi;
    for (const [kind, label] of [["current", "Current paper"], ["existing", "Existing DOI record"]]) {
      const card = node(`[data-record="${kind}"]`), paper = review[kind];
      line(card, "div", label, "doi-label");
      line(card, "h3", paper.title || "Untitled paper");
      line(card, "p", paper.authors || "Authors unavailable");
      line(card, "p", [paper.journal, paper.publication_date].filter(Boolean).join(" · "));
      line(card, "p", paper.storage_key, "doi-key");
      line(card, "p", `Default: ${paper.default_file || "No local file"} · ${paper.file_count} file(s)`);
      line(card, "p", [...(paper.locations || []), ...(paper.monitors || [])].join("\n") || "No Library location");
    }
    node("[data-merge-description]").textContent =
      `Keep the current Gewu Key${review.current.default_file ? ", Default PDF" : ""} and location${review.main_location ? ` (${review.main_location})` : ""}. Other managed files move to its Associated Files. Keep all folder and Monitor entries; Monitor shows the shared Library status.`;
    document.body.append(backdrop);
    const confirm = node("[data-confirm]"), status = node(".doi-status");
    let busy = false;
    const close = result => { if (busy) return; backdrop.remove(); focus?.focus?.(); resolve(result); };
    node(".settings-modal-close").onclick = () => close(null);
    node("[data-cancel]").onclick = () => close(null);
    backdrop.addEventListener("change", () => {
      confirm.disabled = false;
      confirm.textContent = node("input:checked").value === "merge" ? "Merge Records" : "Correct DOI Assignment";
    });
    backdrop.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(null); }
      if (event.key === "Tab") {
        const controls = [...backdrop.querySelectorAll("button:not(:disabled),input:not(:disabled)")];
        const index = controls.indexOf(document.activeElement);
        if ((event.shiftKey && index <= 0) || (!event.shiftKey && index === controls.length - 1)) {
          event.preventDefault(); controls[event.shiftKey ? controls.length - 1 : 0].focus();
        }
      }
    });
    confirm.onclick = async () => {
      if (busy || !node("input:checked")) return;
      busy = true; status.textContent = "Applying your choice…";
      backdrop.querySelectorAll("button,input").forEach(el => { el.disabled = true; });
      try {
        const response = await fetch("/api/library/preprint-identifier", {
          method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({
            kind: "doi", paper_id: review.current.paper_id, identifier: review.doi,
            item_id: review.item_id, fingerprint: review.fingerprint, conflict_action: node("input:checked").value
          })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || "The change could not be completed.");
        busy = false; close(result);
      } catch (error) {
        busy = false; status.textContent = error.message;
        backdrop.querySelectorAll("button,input").forEach(el => { el.disabled = false; });
      }
    };
    node("section").focus();
  });
})();
