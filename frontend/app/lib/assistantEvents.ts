// Asistanı menüden açma: mobilde yüzen "Asistan" düğmesi gizlenir (diğer düğmelerin üstüne biniyordu); menüdeki
// "Asistan" satırı bu olayı yayınlar, asistanı barındıran bileşen (AssistantFab / charts sayfası) dinleyip açar.
export const OPEN_ASSISTANT_EVENT = "open-assistant";

export function openAssistant(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(OPEN_ASSISTANT_EVENT));
}
