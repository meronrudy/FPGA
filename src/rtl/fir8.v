// FIR8 - Parameterized Moving Average FIR Filter (Q1.15)
// Module name retained: fir8
// Parameters:
//   - TAPS      : number of taps (4, 8, 16, 32). Must be a power-of-two.
//   - PIPELINE  : 0 = baseline latency, 1 = add +1-cycle output register.
//   - ROUND     : 1 = round-to-nearest before shift; 0 = truncate.
//   - SAT       : 1 = saturate to Q1.15; 0 = wrap/truncate to 16-bit.
// Implementation notes:
//   - Delay line size equals TAPS. On each valid_in, the new sample is inserted at taps[0].
//   - The average is computed as sum(window) >>> SHIFT, where SHIFT = $clog2(TAPS).
//   - Rounding: pre-add/sub (1 << (SHIFT-1)) based on sign of sum (symmetric).
//   - Valid protocol: ready_in is always 1. valid_out asserts 1 cycle AFTER the window fills,
//     plus +1 cycle if PIPELINE=1. This matches test expectation offset = (1 + PIPELINE).
//   - Target clock: 12 MHz base (period 83.333 ns) as used in CI timing checks.
//
// Timing summary (valid_in held high):
//   - First valid_out occurs one cycle after accepting TAPS samples,
//     plus +1 cycle if PIPELINE=1.
//
// Safety/constraints:
//   - Elaboration-time parameter checks ensure TAPS ∈ {4,8,16,32} and PIPELINE/ROUND/SAT ∈ {0,1}.
//   - Q1.15 saturation clamps outputs to [-32768, 32767] when SAT=1.
//
// Copyright:
//   - MIT Licensed, see LICENSE.
//
// 12 MHz base clock target for CI (83.333 ns period).
//
`default_nettype none

module fir8 #(
  parameter integer TAPS     = 8,  // allowed: 4, 8, 16, 32
  parameter integer PIPELINE = 0,  // 0 or 1
  parameter integer ROUND    = 1,  // 0 or 1
  parameter integer SAT      = 1   // 0 or 1
)(
  input  wire                 clk,
  input  wire                 rst,          // synchronous, active-high
  input  wire signed [15:0]   sample_in,    // Q1.15
  input  wire                 valid_in,
  output wire                 ready_in,     // always 1 (no backpressure)
  output reg  signed [15:0]   sample_out,   // Q1.15
  output reg                  valid_out
);

  // Derived constants
  localparam integer SHIFT = $clog2(TAPS);
  localparam integer SUM_W = 16 + SHIFT + 1; // growth + sign
  localparam integer CNT_W = (TAPS <= 2) ? 2 : $clog2(TAPS + 1);

  // Parameter validation (elaboration-time)
  generate
    if (!((TAPS==4)||(TAPS==8)||(TAPS==16)||(TAPS==32))) begin : g_bad_taps
      initial $error("fir8: TAPS must be one of 4,8,16,32 (got %0d)", TAPS);
    end
    if (!((PIPELINE==0)||(PIPELINE==1))) begin : g_bad_pipe
      initial $error("fir8: PIPELINE must be 0 or 1 (got %0d)", PIPELINE);
    end
    if (!((ROUND==0)||(ROUND==1))) begin : g_bad_round
      initial $error("fir8: ROUND must be 0 or 1 (got %0d)", ROUND);
    end
    if (!((SAT==0)||(SAT==1))) begin : g_bad_sat
      initial $error("fir8: SAT must be 0 or 1 (got %0d)", SAT);
    end
  endgenerate

  // Always-ready in Phase 1
  assign ready_in = 1'b1;

  // Tap delay line
  reg signed [15:0] taps [0:TAPS-1];
  reg [CNT_W-1:0]   fill_cnt; // counts up to TAPS

  // Combinational sum/round/avg (current window including sample_in)
  reg signed [SUM_W-1:0] sum_comb;
  reg signed [SUM_W-1:0] bias_comb;
  reg signed [SUM_W-1:0] avg_comb;

  // Registered average for baseline output stage
  reg signed [SUM_W-1:0] avg_reg;

  // Optional output pipeline stage
  reg signed [15:0] out_pipe;
  reg               valid_pipe;

  // Window-full detection and one-cycle delay to meet latency spec
  wire window_full_now = (fill_cnt >= (TAPS-1)[CNT_W-1:0]);
  reg  window_full_q;

  // Saturation helper to Q1.15
  function automatic signed [15:0] sat16;
    input signed [SUM_W-1:0] v;
    begin
      if (SAT) begin
        if (v > $signed(16'sd32767))       sat16 = 16'sd32767;
        else if (v < $signed(-16'sd32768)) sat16 = -16'sd32768;
        else                                sat16 = v[15:0];
      end else begin
        sat16 = v[15:0]; // wrap/truncate
      end
    end
  endfunction

  integer i;

  // Combinational math for current-input window
  always @* begin
    // Sum current sample and previous TAPS-1 samples
    sum_comb = $signed(sample_in);
    for (i = 0; i < TAPS-1; i = i + 1) begin
      sum_comb = sum_comb + $signed(taps[i]);
    end
    // Rounding bias
    if (ROUND) begin
      bias_comb = (sum_comb >= 0) ? ($signed(1) <<< (SHIFT-1)) : -($signed(1) <<< (SHIFT-1));
    end else begin
      bias_comb = {SUM_W{1'b0}};
    end
    // Average (arithmetic shift)
    avg_comb = (sum_comb + bias_comb) >>> SHIFT;
  end

  always @(posedge clk) begin
    if (rst) begin
      for (i = 0; i < TAPS; i = i + 1) begin
        taps[i] <= 16'sd0;
      end
      fill_cnt      <= {CNT_W{1'b0}};
      avg_reg       <= {SUM_W{1'b0}};
      out_pipe      <= 16'sd0;
      valid_pipe    <= 1'b0;
      sample_out    <= 16'sd0;
      valid_out     <= 1'b0;
      window_full_q <= 1'b0;
    end else begin
      // Default deassertions
      valid_out     <= 1'b0;
      if (PIPELINE) valid_pipe <= 1'b0;

      if (valid_in && ready_in) begin
        // Register average from current window (baseline single stage)
        avg_reg <= avg_comb;

        // Shift delay line and insert new sample
        for (i = TAPS-1; i > 0; i = i - 1) begin
          taps[i] <= taps[i-1];
        end
        taps[0] <= sample_in;

        // Fill counter up to TAPS
        if (fill_cnt != TAPS[CNT_W-1:0]) begin
          fill_cnt <= fill_cnt + {{(CNT_W-1){1'b0}}, 1'b1};
        end

        // Delay 'window full' by one cycle for baseline latency
        window_full_q <= window_full_now;

        // Output generation
        if (PIPELINE) begin
          // Stage 1: compute and capture output, align valid (+1)
          out_pipe   <= sat16(avg_reg);
          valid_pipe <= window_full_q;
        end else begin
          // Baseline: one-cycle latency after window full
          sample_out <= sat16(avg_reg);
          valid_out  <= window_full_q;
        end
      end

      // Optional extra output pipeline stage
      if (PIPELINE) begin
        sample_out <= out_pipe;
        valid_out  <= valid_pipe;
      end
    end
  end

endmodule

`default_nettype wire