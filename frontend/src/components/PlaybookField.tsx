/** Decorative field artwork, not a live lineup or a projection. */
export default function PlaybookField() {
  return (
    <div className="playbook-field" aria-hidden="true">
      <svg viewBox="0 0 400 460" fill="none">
        <rect
          x="28"
          y="20"
          width="344"
          height="420"
          rx="4"
          stroke="currentColor"
          strokeOpacity=".25"
        />
        {[80, 140, 200, 260, 320, 380].map((y) => (
          <g key={y}>
            <path
              d={`M28 ${y}h344`}
              stroke="currentColor"
              strokeOpacity=".16"
            />
            {[122, 278].map((x) => (
              <path
                key={x}
                d={`M${x} ${y - 24}v8m0 8v8m0 8v8`}
                stroke="currentColor"
                strokeOpacity=".35"
              />
            ))}
          </g>
        ))}
        <path
          d="M103 331V216l71-75M295 329V216l-60-55M201 365V253"
          stroke="#c9e8a5"
          strokeWidth="2"
          strokeDasharray="6 7"
        />
        <path
          d="m158 141 16 0 0 16M235 177v-16h16m-58 103 8-11 8 11"
          stroke="#c9e8a5"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {[
          [103, 340, "WR"],
          [201, 374, "QB"],
          [295, 340, "WR"],
          [157, 310, "RB"],
          [246, 310, "TE"],
        ].map(([x, y, label]) => (
          <g key={label + String(x)}>
            <circle
              cx={x}
              cy={y}
              r="20"
              fill="#1d4833"
              stroke="#d8e9c5"
              strokeWidth="1.5"
            />
            <text
              x={x}
              y={Number(y) + 4}
              textAnchor="middle"
              fill="#e5efdc"
              fontSize="10"
              fontFamily="sans-serif"
              fontWeight="600"
            >
              {label}
            </text>
          </g>
        ))}
        <text
          x="200"
          y="65"
          textAnchor="middle"
          fill="currentColor"
          fillOpacity=".35"
          fontSize="11"
          fontFamily="monospace"
          letterSpacing="6"
        >
          MAKE YOUR MOVE
        </text>
      </svg>
    </div>
  );
}
