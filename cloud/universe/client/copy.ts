/**
 * Copy buttons for the commands on the landing and download pages: a
 * `<button class="copy" data-copy="ID">` next to `<code id="ID">` copies the code's text.
 *
 * Where the clipboard is refused (an insecure origin, a denied permission), the button
 * selects the text instead, so it can be copied by hand. Either way the button says what
 * happened for two seconds. Without the script the command is plain text to select.
 */

import { MESSAGES, pageLanguage } from "./messages";

export function copyButtons(root: ParentNode = document): void {
  const t = MESSAGES[pageLanguage(document.documentElement.lang)];
  for (const button of root.querySelectorAll<HTMLButtonElement>("button[data-copy]")) {
    let reset = 0;
    button.addEventListener("click", async () => {
      const source = document.getElementById(button.dataset.copy ?? "");
      if (source === null) return;
      try {
        await navigator.clipboard.writeText(source.textContent ?? "");
        button.textContent = t.copied;
      } catch {
        const range = document.createRange();
        range.selectNodeContents(source);
        window.getSelection()?.removeAllRanges();
        window.getSelection()?.addRange(range);
        button.textContent = t.selected;
      }
      window.clearTimeout(reset);
      reset = window.setTimeout(() => {
        button.textContent = t.copy;
      }, 2000);
    });
  }
}
