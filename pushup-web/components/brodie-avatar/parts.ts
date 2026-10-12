export type AvatarParts = {
  chest: number;
  triceps: number;
  delts: number;
  core: number;
};

export function avatarParts(level: number): AvatarParts {
  const clamped = Number.isNaN(level) ? 1 : Math.min(10, Math.max(1, level));
  const progress = (clamped - 1) / 9;

  return {
    chest: 1 + progress * 0.6,
    triceps: 1 + progress * 0.75,
    delts: 1 + progress * 0.65,
    core: 1 + progress * 0.4,
  };
}
