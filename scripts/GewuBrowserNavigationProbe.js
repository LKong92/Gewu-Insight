// One-shot boundary check in an isolated content world. No values, text,
// credentials, persistent event hooks, timers, or mutation observers are read.
(direction) => {
  if (document.contentType !== "text/html" || document.visibilityState !== "visible") return false;
  let active = document.activeElement;
  while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
  if (!active || active.closest('input,textarea,select,iframe,object,embed,canvas,[contenteditable]:not([contenteditable="false"]),[role="textbox"],[role="combobox"],[role="listbox"],[role="tree"],[role="grid"],[role="menu"],[role="slider"],[role="spinbutton"],[role="tablist"],[aria-activedescendant]')) return false;
  // Custom controls have unknown key contracts. Leave their arrows alone.
  if (!["BODY", "HTML", "A", "BUTTON", "DIV", "SECTION", "MAIN", "ARTICLE"].includes(active.tagName) || active.getAttribute("role")
      || (active.hasAttribute("tabindex") && !["A", "BUTTON"].includes(active.tagName))) return false;
  for (let element = active; element; element = element.parentElement) {
    if (direction === "up" ? element.scrollTop > 1 : Math.abs(element.scrollLeft) > 1) return false;
  }
  const scroll = document.scrollingElement;
  return !!scroll && (direction === "up" ? scroll.scrollTop <= 1 : Math.abs(scroll.scrollLeft) <= 1);
}
