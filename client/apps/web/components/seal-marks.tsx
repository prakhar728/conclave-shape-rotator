/**
 * Roman ornaments used across the Conclave UI.
 * Laurel wreath, SPQR-style seal, Roman arch divider.
 */

export function Laurel({
  className = "h-12 w-12",
  color = "currentColor",
}: {
  className?: string
  color?: string
}) {
  return (
    <svg viewBox="0 0 64 64" className={className} fill="none" stroke={color} strokeWidth="1.5">
      <path d="M14 50 Q8 32 18 14" strokeLinecap="round" />
      {[0, 1, 2, 3, 4, 5].map((i) => {
        const t = i / 5
        const x = 14 + (18 - 14) * (1 - t) - 4 * t
        const y = 50 - 36 * t
        return (
          <ellipse
            key={`l${i}`}
            cx={x}
            cy={y}
            rx="3.2"
            ry="1.4"
            transform={`rotate(${-50 + 12 * i} ${x} ${y})`}
            fill={color}
            opacity="0.85"
          />
        )
      })}
      <path d="M50 50 Q56 32 46 14" strokeLinecap="round" />
      {[0, 1, 2, 3, 4, 5].map((i) => {
        const t = i / 5
        const x = 50 - (50 - 46) * (1 - t) + 4 * t
        const y = 50 - 36 * t
        return (
          <ellipse
            key={`r${i}`}
            cx={x}
            cy={y}
            rx="3.2"
            ry="1.4"
            transform={`rotate(${50 - 12 * i} ${x} ${y})`}
            fill={color}
            opacity="0.85"
          />
        )
      })}
      <path d="M28 50 Q32 54 36 50" strokeLinecap="round" />
    </svg>
  )
}

export function SpqrSeal({
  className = "h-24 w-24",
  label = "SPQR",
  sub = "CONCLAVIUM",
}: {
  className?: string
  label?: string
  sub?: string
}) {
  return (
    <svg viewBox="0 0 120 120" className={className}>
      <defs>
        <radialGradient id="seal-grad" cx="0.5" cy="0.5" r="0.6">
          <stop offset="0%" stopColor="#7a3258" />
          <stop offset="100%" stopColor="#5d2545" />
        </radialGradient>
      </defs>
      <circle cx="60" cy="60" r="54" fill="url(#seal-grad)" stroke="#c08a3e" strokeWidth="2" />
      <circle cx="60" cy="60" r="46" fill="none" stroke="#c08a3e" strokeWidth="0.6" opacity="0.7" />
      {Array.from({ length: 18 }).map((_, i) => {
        const a = (i / 18) * Math.PI * 2
        const r = 41
        const x = 60 + Math.cos(a) * r
        const y = 60 + Math.sin(a) * r
        const deg = (a * 180) / Math.PI + 90
        return (
          <ellipse
            key={i}
            cx={x}
            cy={y}
            rx="2.8"
            ry="1.2"
            fill="#c08a3e"
            opacity="0.9"
            transform={`rotate(${deg} ${x} ${y})`}
          />
        )
      })}
      <text
        x="60"
        y="68"
        textAnchor="middle"
        fontFamily="Cinzel, serif"
        fontWeight="900"
        fontSize="22"
        fill="#f0ead8"
        letterSpacing="2"
      >
        {label}
      </text>
      <text
        x="60"
        y="86"
        textAnchor="middle"
        fontFamily="Cinzel, serif"
        fontSize="7"
        fill="#c08a3e"
        letterSpacing="2"
      >
        {sub}
      </text>
    </svg>
  )
}

export function ArchDivider({ className = "w-full h-12" }: { className?: string }) {
  return (
    <svg viewBox="0 0 1200 60" className={className} preserveAspectRatio="none">
      <line x1="0" y1="58" x2="540" y2="58" stroke="#cabc99" strokeWidth="1" />
      <line x1="660" y1="58" x2="1200" y2="58" stroke="#cabc99" strokeWidth="1" />
      <path
        d="M540 58 L540 30 Q540 8 600 8 Q660 8 660 30 L660 58"
        fill="none"
        stroke="#cabc99"
        strokeWidth="1"
      />
      <rect x="592" y="4" width="16" height="14" fill="#cabc99" opacity="0.6" />
      <circle cx="600" cy="35" r="6" fill="none" stroke="#c08a3e" strokeWidth="1" />
      <circle cx="600" cy="35" r="2" fill="#c08a3e" />
    </svg>
  )
}
