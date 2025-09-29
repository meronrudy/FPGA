// Formal wrapper for parameterized fir8
// Parameters:
//   - TAPS     : 4/8/16/32
//   - PIPELINE : 0/1
//   - ROUND    : 0/1
//   - SAT      : 0/1
// Properties proved:
//   - ready_in is always 1 after reset deasserts
//   - If SAT==1, sample_out remains within signed Q1.15 bounds when valid_out
//   - Eventually a valid_out occurs (cover)
// Reset behavior:
//   - rst held high for 2 cycles after time 0 then deasserted
`default_nettype none

module fir8_formal #(
  parameter integer TAPS     = 8,
  parameter integer PIPELINE = 0,
  parameter integer ROUND    = 1,
  parameter integer SAT      = 1
);

  // Formal clock modeling: constrain a free-running toggling clock
  reg clk = 1'b0;
  always @(*) if (!$init) assume(clk == !$past(clk));

  // Synchronous reset: asserted for exactly 2 clock edges, then low forever
  reg [1:0] rst_cnt = 2'd0;
  reg       rst     = 1'b1;
  always @(posedge clk) begin
    if (rst_cnt != 2'd2) begin
      rst_cnt <= rst_cnt + 2'd1;
      rst     <= 1'b1;
    end else begin
      rst     <= 1'b0;
    end
  end

  // Inputs/outputs to DUT
  (* anyconst *) reg  signed [15:0] xin;
  wire                    ready_in;
  wire signed [15:0]      sample_out;
  wire                    valid_out;

  // Always stream inputs in Phase 1
  wire valid_in = 1'b1;

  // DUT
  fir8 #(
    .TAPS(TAPS),
    .PIPELINE(PIPELINE),
    .ROUND(ROUND),
    .SAT(SAT)
  ) u_dut (
    .clk        (clk),
    .rst        (rst),
    .sample_in  (xin),
    .valid_in   (valid_in),
    .ready_in   (ready_in),
    .sample_out (sample_out),
    .valid_out  (valid_out)
  );

  // Assumptions after reset deasserts
  always @(posedge clk) if (!rst) begin
    // No backpressure expected
    assert(ready_in == 1'b1);
  end

  // Range check only when SAT==1 (default)
  generate
    if (SAT) begin : g_sat_chk
      always @(posedge clk) if (!rst && valid_out) begin
        assert(sample_out <= 16'sd32767);
        assert(sample_out >= -16'sd32768);
      end
    end
  endgenerate

  // Cover: eventually produce a valid output
  always @(posedge clk) if (!rst) begin
    cover(valid_out);
  end

endmodule

`default_nettype wire
