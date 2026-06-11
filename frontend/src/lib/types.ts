export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface LeagueConnection {
  id: string;
  platform: string;
  league_id: string;
  league_name: string | null;
  season: number;
  scoring_type: string | null;
  roster_positions: string[] | null;
  team_id: string | null;
  last_synced_at: string | null;
}

export interface SleeperLeagueOption {
  league_id: string;
  name: string;
  season: string;
  total_rosters: number;
  scoring_type: string | null;
}

export interface SleeperLookup {
  user_id: string;
  username: string;
  leagues: SleeperLeagueOption[];
}

export interface PlayerCard {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  injury_status?: string | null;
  status?: string | null;
}

export interface Roster {
  team_id: string;
  owner_name: string | null;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  starters: PlayerCard[];
  bench: PlayerCard[];
}

export interface Matchup {
  week: number;
  user_team: Roster | null;
  opponent_team: Roster | null;
}

export interface StandingsEntry {
  team_id: string;
  owner_name: string | null;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
}

export interface WaiverPlayer {
  player: PlayerCard;
  trending_count: number | null;
  recent_ppr_avg: number | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  intent?: string | null;
  created_at?: string;
}

export interface WeeklyStat {
  season: number;
  week: number;
  opponent: string | null;
  targets: number;
  receptions: number;
  receiving_yards: number;
  rush_yards: number;
  pass_yards: number;
  fantasy_points_ppr: number | null;
  fantasy_points_half: number | null;
  fantasy_points_std: number | null;
}

export interface InjuryEntry {
  id: string;
  name: string;
  position: string | null;
  team: string | null;
  injury_status: string | null;
  injury_body_part: string | null;
}
