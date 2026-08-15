// Nuxt UI gives every solid variant one shared foreground that flips with the color mode, which
// leaves a filled button reading white in one mode and near-black in the other. These colors are
// fixed rather than mode-dependent, so their text is too. Neutral is left alone, being the one
// color that does track the mode.
const solidColors = ['primary', 'success', 'warning', 'error', 'info'] as const

const solidOnWhiteText = solidColors.map((color) => ({
  color,
  variant: 'solid' as const,
  class: 'text-white',
}))

export default defineAppConfig({
  ui: {
    colors: {
      primary: 'ceres',
      success: 'green',
      warning: 'amber',
      error: 'red',
      info: 'cyan',
      neutral: 'neutral',
    },
    button: { compoundVariants: solidOnWhiteText },
    badge: { compoundVariants: solidOnWhiteText },
  },
})
