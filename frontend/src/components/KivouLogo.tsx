import styles from './KivouLogo.module.css'

export function KivouMark({ size = 32, title }: { size?: number; title?: string }) {
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={styles.mark}
      role={title ? 'img' : 'presentation'}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="62" y1="50" x2="81" y2="50" />
        <line x1="74" y1="50" x2="74" y2="55" />
        <line x1="58.49" y1="58.49" x2="71.92" y2="71.92" />
        <line x1="66.97" y1="66.97" x2="63.44" y2="70.51" />
        <line x1="50" y1="62" x2="50" y2="81" />
        <line x1="50" y1="74" x2="45" y2="74" />
        <line x1="41.51" y1="58.49" x2="28.08" y2="71.92" />
        <line x1="33.03" y1="66.97" x2="29.49" y2="63.44" />
        <line x1="38" y1="50" x2="19" y2="50" />
        <line x1="26" y1="50" x2="26" y2="45" />
        <line x1="41.51" y1="41.51" x2="28.08" y2="28.08" />
        <line x1="33.03" y1="33.03" x2="36.56" y2="29.49" />
        <line x1="50" y1="38" x2="50" y2="19" />
        <line x1="50" y1="26" x2="55" y2="26" />
        <line x1="58.49" y1="41.51" x2="71.92" y2="28.08" />
        <line x1="66.97" y1="33.03" x2="70.51" y2="36.56" />
        <circle cx="85.23" cy="64.24" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="64.85" cy="84.98" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="35.76" cy="85.23" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="15.02" cy="64.85" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="14.77" cy="35.76" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="35.15" cy="15.02" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="64.24" cy="14.77" r="2.2" fill="currentColor" stroke="none" />
        <circle cx="84.98" cy="35.15" r="2.2" fill="currentColor" stroke="none" />
      </g>
    </svg>
  )
}

export function KivouLogo({
  size = 'md',
  baseline,
  tone = 'default',
}: {
  size?: 'sm' | 'md' | 'lg'
  baseline?: string
  tone?: 'default' | 'inverse' | 'mint'
}) {
  const markSize = size === 'lg' ? 44 : size === 'sm' ? 24 : 32
  return (
    <span className={`${styles.lockup} ${styles[size]} ${tone === 'inverse' ? styles.inverse : tone === 'mint' ? styles.mint : ''}`}>
      <KivouMark size={markSize} />
      <span className={styles.text}>
        <span className={styles.wordmark}>KIVOU</span>
        {baseline ? <span className={styles.baseline}>{baseline}</span> : null}
      </span>
    </span>
  )
}
