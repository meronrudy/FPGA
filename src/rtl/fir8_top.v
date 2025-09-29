// fir8_top - iCEBreaker (iCE40UP5K-SG48) top-level
// Parameters:
//   - TAPS     : 4/8/16/32, forwarded to fir8
//   - PIPELINE : 0/1, forwarded to fir8
// Interface:
//   - clk : 12 MHz external XO (constraints/icebreaker.pcf pin 35)
//   - led : LED D1 observable output (pcf pin 39)
// Behavior:
//   - Synchronous power-on reset (POR) holds reset for initial cycles
//   - Heartbeat divider for user-visible activity
//   - 16-bit Fibonacci LFSR stimulus drives fir8.sample_in; valid_in = 1
//   - Observable path: LED = heartbeat_bit XOR fir.sample_out[15]
// Synthesis notes:
//   - Use (* keep *) on stimulus nets to avoid pruning
//   - Base target period for CI timing is 83.333 ns (12 MHz)
//
// Mapping (per constraints/icebreaker.pcf):
//   set_io clk 35
//   set_io led 39
//
`default_nettype none

module fir8_top #(
  parameter integer TAPS     = 8,
  parameter integer PIPELINE = 0
)(
  input  wire clk,
  output wire led
);

  // Power-On Reset (synchronous, active-high)
  reg [15:0] por_cnt = 16'd0;
  reg        rst     = 1'b1;

  always @(posedge clk) begin
    if (por_cnt != 16'hFFFF) begin
      por_cnt <= por_cnt + 16'd1;
      rst     <= 1'b1;
    end else begin
      rst     <= 1'b0;
    end
  end

  // Heartbeat divider (~0.7 Hz with 12 MHz clk when observing hb[23])
  reg [23:0] hb = 24'd0;
  always @(posedge clk) begin
    if (rst) begin
      hb <= 24'd0;
    end else begin
      hb <= hb + 24'd1;
    end
  end

  // 16-bit Fibonacci LFSR (x^16 + x^14 + x^13 + x^11 + 1)
  // taps: bits [15], [13], [12], [10]
  (* keep = "true" *) reg  [15:0] lfsr;
  (* keep = "true" *) wire        lfsr_fb = lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10];

  always @(posedge clk) begin
    if (rst) begin
      lfsr <= 16'hACE1; // non-zero seed
    end else begin
      lfsr <= {lfsr[14:0], lfsr_fb};
    end
  end

  // FIR stimulus and handshake
  (* keep = "true" *) wire signed [15:0] stim     = lfsr; // reinterpret as Q1.15
  (* keep = "true" *) wire              valid_in = 1'b1;  // continuous streaming
  wire                                   ready_in;
  (* keep = "true" *) wire signed [15:0] sample_out;
  wire                                   valid_out;

  // FIR instance; ROUND/SAT left at defaults (overridden in sim/synth flows)
  fir8 #(
    .TAPS(TAPS),
    .PIPELINE(PIPELINE)
  ) u_fir8 (
    .clk        (clk),
    .rst        (rst),
    .sample_in  (stim),
    .valid_in   (valid_in),
    .ready_in   (ready_in),
    .sample_out (sample_out),
    .valid_out  (valid_out)
  );

  // Observable path: heartbeat XOR FIR MSB
  (* keep = "true" *) wire fir_msb = sample_out[15];
  assign led = hb[23] ^ fir_msb;

endmodule

`default_nettype wire