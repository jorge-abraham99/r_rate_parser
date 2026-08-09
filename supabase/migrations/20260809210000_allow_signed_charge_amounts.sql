-- Charge lines can represent discounts and signed freight adjustments.
alter table public.rate_charge_lines
  drop constraint if exists rate_charge_lines_amount_check;
