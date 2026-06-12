import { BookOpen, Clock3, MapPin, Swords, Wallet } from "lucide-react";

import type { GameStatus, PartyMon } from "../api";

const ALL_BADGES = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth"];

function hpTone(hp: number, maxHp: number): string {
  if (maxHp <= 0) return "ok";
  const ratio = hp / maxHp;
  if (ratio <= 0.2) return "danger";
  if (ratio <= 0.5) return "warn";
  return "ok";
}

function PartyCard({ mon }: { mon: PartyMon }) {
  const fainted = mon.hp <= 0;
  const percent = mon.max_hp > 0 ? Math.max(0, Math.min(100, (mon.hp / mon.max_hp) * 100)) : 0;
  return (
    <div className={`party-card${fainted ? " fainted" : ""}`}>
      <div className="party-card-top">
        <strong title={mon.species}>{mon.nickname}</strong>
        <span className="party-level">Lv {mon.level}</span>
      </div>
      {mon.nickname !== mon.species && <span className="party-species">{mon.species}</span>}
      <div className="hp-bar" title={`${mon.hp}/${mon.max_hp} HP`}>
        <div className={`hp-fill hp-${hpTone(mon.hp, mon.max_hp)}`} style={{ width: `${percent}%` }} />
      </div>
      <div className="party-card-bottom">
        <span>{mon.hp}/{mon.max_hp}</span>
        {fainted ? (
          <span className="status-chip status-fnt">FNT</span>
        ) : mon.status ? (
          <span className={`status-chip status-${mon.status.toLowerCase()}`}>{mon.status}</span>
        ) : null}
      </div>
    </div>
  );
}

export function StatusPanel({ status }: { status: GameStatus | null }) {
  if (!status) {
    return null;
  }
  return (
    <section className="status-panel" aria-label="Game status">
      <div className="trainer-row">
        <span className="trainer-stat" title="Current location">
          <MapPin size={13} />
          {status.map_name ?? (status.map_id != null ? `Map ${status.map_id}` : "–")}
        </span>
        <span className="trainer-stat" title="Money">
          <Wallet size={13} />
          ₽{status.money?.toLocaleString() ?? "–"}
        </span>
        <span className="trainer-stat" title="Pokedex owned / seen">
          <BookOpen size={13} />
          {status.pokedex_owned ?? 0} owned · {status.pokedex_seen ?? 0} seen
        </span>
        <span className="trainer-stat" title="In-game play time">
          <Clock3 size={13} />
          {status.play_time ?? "–"}
        </span>
        <span className="badge-row" title={status.badges.length ? `Badges: ${status.badges.join(", ")}` : "No badges yet"}>
          {ALL_BADGES.map((badge) => (
            <span
              key={badge}
              className={`badge-dot${status.badges.includes(badge) ? " earned" : ""}`}
              title={`${badge} Badge${status.badges.includes(badge) ? "" : " (not earned)"}`}
            />
          ))}
        </span>
      </div>

      {status.battle && (
        <div className="battle-banner">
          <Swords size={14} />
          <span>
            {status.battle.kind === "trainer" ? "Trainer battle" : "Wild battle"}
            {status.battle.enemy_species ? ` vs ${status.battle.enemy_species}` : ""}
            {status.battle.enemy_level != null ? ` (Lv ${status.battle.enemy_level}` : ""}
            {status.battle.enemy_hp != null ? `, ${status.battle.enemy_hp} HP)` : status.battle.enemy_level != null ? ")" : ""}
          </span>
        </div>
      )}

      {status.party.length > 0 ? (
        <div className="party-grid">
          {status.party.map((mon) => (
            <PartyCard key={mon.slot} mon={mon} />
          ))}
        </div>
      ) : (
        <p className="party-empty">No Pokemon in party yet.</p>
      )}
    </section>
  );
}
