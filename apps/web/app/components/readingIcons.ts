import type { Measure } from "../../lib/humanize";
import type { IconName } from "./ui/Icon";
export const measureIcon: Record<Measure, IconName> = {
  waves: "waves",
  wind: "windsock",
  current: "current",
  sst: "thermo",
  warnings: "pennant",
  float: "float",
  normal: "compass",
  other: "info",
};
