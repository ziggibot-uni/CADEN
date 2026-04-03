import { cadenColors } from "../../caden-colors.js";

export default {
  content: ["./index.html", "./src/**/*.{jsx,js}"],
  theme: {
    extend: {
      colors: cadenColors,
    },
  },
};
