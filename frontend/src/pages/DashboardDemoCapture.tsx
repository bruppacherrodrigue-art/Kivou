import { useI18n } from '../i18n'
import { KivouLogo } from '../components/KivouLogo'
import { Badge } from '../components/Surfaces'
import { publicDemoSignal } from '../content/publicDemoSignal'
import { dashboardDemoFeed, dashboardDemoVolumes } from '../content/landingDashboardDemo'
import {
  BellIcon,
  BuildingIcon,
  CheckIcon,
  DocumentIcon,
  NeedIcon,
  SignalsIcon,
  TargetIcon,
} from '../assets/Icons'
import styles from './DashboardDemoCapture.module.css'

export function DashboardDemoCapture() {
  const { t, locale, date } = useI18n()
  const copy = t.landing.how.demo
  const signal = publicDemoSignal

  const nav = [
    { label: copy.navOverview, Icon: DocumentIcon },
    { label: copy.navSignals, Icon: SignalsIcon, active: true },
    { label: copy.navCompanies, Icon: BuildingIcon },
    { label: copy.navAlerts, Icon: BellIcon },
    { label: copy.navProfile, Icon: TargetIcon },
    { label: copy.navSettings, Icon: NeedIcon },
  ]

  return (
    <main className={styles.capture} id="kivou-dashboard-capture">
      <aside className={styles.sidebar}>
        <KivouLogo size="md" />
        <nav aria-label={t.nav.mainNavigation}>
          <ul className={styles.navList}>
            {nav.map(({ label, Icon, active }) => (
              <li key={label}>
                <span className={`${styles.navItem} ${active ? styles.navActive : ''}`}>
                  <Icon aria-hidden="true" />
                  {label}
                </span>
              </li>
            ))}
          </ul>
        </nav>
        <div className={styles.demoAccount}>
          <span aria-hidden="true">KD</span>
          <strong>{copy.account}</strong>
        </div>
      </aside>

      <section className={styles.workspace} aria-label={copy.topTitle}>
        <header className={styles.topbar}>
          <div>
            <p className={styles.previewBadge}>{copy.previewBadge}</p>
            <h1>{copy.topTitle}</h1>
          </div>
          <div className={styles.toolbar}>
            <span>{copy.search}</span>
            <span>{copy.activeProfile}</span>
            <span>{copy.territory}</span>
          </div>
        </header>

        <div className={styles.columns}>
          <aside className={styles.feed} aria-label={copy.navSignals}>
            {dashboardDemoFeed.map((item, index) => (
              <article
                className={`${styles.feedCard} ${index === 0 ? styles.feedSelected : ''}`}
                key={item.company}
              >
                <div className={styles.feedHead}>
                  <strong>{item.company}</strong>
                  {index === 0 ? <span>{copy.selected}</span> : null}
                </div>
                <p>{item.event[locale]}</p>
                <p className={styles.feedMeta}>
                  {item.amount} · {item.region[locale]}
                </p>
                <p className={styles.feedTags}>
                  {item.freshness[locale]} · {item.fit[locale]}
                </p>
                <p className={styles.feedReason}>{item.reason[locale]}</p>
              </article>
            ))}
          </aside>

          <section className={styles.signalDetail} aria-label={copy.opportunity}>
            <p className={styles.eyebrow}>{copy.opportunity}</p>
            <h2>{copy.signalTitle}</h2>
            <p className={styles.summary}>{copy.summary}</p>

            <div className={styles.badges}>
              <Badge tone="positive">{copy.verifiedEvent}</Badge>
              <Badge tone="warm">{copy.goodTiming}</Badge>
              <Badge tone="brand">{copy.strongFit}</Badge>
              <Badge tone="muted">{copy.officialSource}</Badge>
            </div>

            <div className={styles.insightGrid}>
              <section className={styles.insight}>
                <h3>{copy.whyRelevantTitle}</h3>
                <p>{copy.whyRelevant}</p>
              </section>
              <section className={styles.insight}>
                <h3>{copy.whyNowTitle}</h3>
                <p>{copy.whyNow}</p>
              </section>
            </div>

            <section className={styles.volumes}>
              <h3>{copy.volumesTitle}</h3>
              <div className={styles.volumeGrid}>
                {dashboardDemoVolumes.map((volume) => (
                  <div className={styles.volumeCard} key={volume.value}>
                    <strong>{volume.value}</strong>
                    <span>{volume.label[locale]}</span>
                  </div>
                ))}
              </div>
            </section>
          </section>

          <aside className={styles.companyPanel} aria-label={copy.companyTitle}>
            <div className={styles.panelHead}>
              <p className={styles.eyebrow}>{copy.companyTitle}</p>
              <Badge tone="positive" icon={<CheckIcon />}>
                {copy.companyVerified}
              </Badge>
            </div>

            <dl className={styles.companyFacts}>
              <div>
                <dt>{copy.legalName}</dt>
                <dd>{signal.winner.legalName}</dd>
              </div>
              <div>
                <dt>{copy.address}</dt>
                <dd>{signal.winner.address}</dd>
              </div>
              <div>
                <dt>{copy.countryRegion}</dt>
                <dd>Deutschland · Niedersachsen</dd>
              </div>
              <div>
                <dt>{copy.website}</dt>
                <dd>huether-gmbh.de</dd>
              </div>
              <div>
                <dt>{copy.phone}</dt>
                <dd>{signal.winner.phone}</dd>
              </div>
              <div>
                <dt>{copy.identifier}</dt>
                <dd>{signal.winner.identifier.value}</dd>
              </div>
              <div>
                <dt>{copy.status}</dt>
                <dd>{copy.companyVerified}</dd>
              </div>
              <div>
                <dt>{copy.updated}</dt>
                <dd>{date(signal.winner.contactVerifiedAt)}</dd>
              </div>
            </dl>

            <section className={styles.actionBox}>
              <h3>{copy.actionTitle}</h3>
              <p>{copy.actionBody}</p>
              <div className={styles.actions}>
                <span>{copy.prepare}</span>
                <span>{copy.save}</span>
                <span>{copy.contacted}</span>
                <span>{copy.source}</span>
              </div>
            </section>
          </aside>
        </div>
      </section>
    </main>
  )
}
