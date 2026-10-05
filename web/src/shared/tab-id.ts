/** Ids that tie a tab to its panel: the panel takes `panelId` and `aria-labelledby={tabId(panelId, tab)}`. */
export const tabId = (panelId: string, id: string) => `${panelId}-tab-${id}`;
