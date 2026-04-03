declare module "../../caden-colors.js" {
  export const cadenColors: Record<string, Record<string, string>>;
  export const cadenColorDefaults: Record<string, string>;
  export const cadenColorGroups: Array<{
    name: string;
    description: string;
    keys: string[];
    labels: string[];
  }>;
  export function hexToRgb(hex: string): string;
  export function rgbToHex(rgb: string): string;
  export function getDefaultsAsRgb(): Record<string, string>;
}
