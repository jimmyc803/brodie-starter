// Front and back body outlines in a 100 x 200 box, one polygon per region, mapped to our muscle keys.
// muscle null = part of the body that is not scored (head, neck, knees, lower back): drawn as plain body.
// Polygon data from react-body-highlighter 2.0.5 (MIT, Copyright (c) 2020 GV79), extracted to shapes.json;
// regions mapped: trapezius -> traps (the neck-to-shoulder slope on front, the upper back on back),
// upper-back -> lats, back-deltoids -> rear_delts, soleus -> calves, inner thigh -> adductors.
// Abductors (outer hip / outer upper thigh) are their own regions, front and back.
import data from "@/lib/body/shapes.json";
import type { MuscleKey } from "@/lib/contract";

export type BodySide = "front" | "back";
export type BodyShape = { muscle: MuscleKey | null; points: string };

export const SHAPES = data as { front: BodyShape[]; back: BodyShape[] };
export const VIEWBOX = { width: 100, height: 220 }; // the back view runs to y = 220
