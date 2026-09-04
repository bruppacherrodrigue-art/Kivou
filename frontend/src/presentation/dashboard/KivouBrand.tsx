export function KivouMark() {
  return (
    <span className="kivou-mark" aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
    </span>
  )
}

export function KivouBrand({ subtitle = 'Signaux commerciaux' }: { subtitle?: string }) {
  return (
    <span className="kivou-brand-lockup">
      <KivouMark />
      <span>
        <strong>KIVOU</strong>
        <small>{subtitle}</small>
      </span>
    </span>
  )
}
