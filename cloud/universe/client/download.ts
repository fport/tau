/**
 * The script of the download page (/download): the star field behind the page
 * (client/starfield.ts) and the copy buttons of its commands (client/copy.ts). The page reads
 * the same without it.
 */

import { copyButtons } from "./copy";
import { starfield } from "./starfield";

starfield();
copyButtons();
