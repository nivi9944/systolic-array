// wave_tb.v : small plain-Verilog testbench that records one 4x4, K = 4 job to a
// VCD file for the README waveform figure (scripts/make_waveform.py) or GTKWave.
//   iverilog -g2005 -o wave.vvp rtl/*.v tb/wave_tb.v && vvp wave.vvp
`timescale 1ns/1ps
module wave_tb;
    localparam N = 4, ACC_W = 32, KW = 7;
    reg clk = 0, rst_n = 0, start = 0, s_valid = 0, m_ready = 0;
    reg  [KW-1:0]    k_len = 0;
    reg  [N*8-1:0]   s_a = 0, s_b = 0;
    wire             busy, done, s_ready, m_valid, m_last;
    wire [N*ACC_W-1:0] m_data;

    sa_top #(.N(N), .ACC_W(ACC_W), .K_MAX(64), .KW(KW)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .k_len(k_len), .busy(busy), .done(done),
        .s_valid(s_valid), .s_ready(s_ready), .s_a(s_a), .s_b(s_b),
        .m_valid(m_valid), .m_ready(m_ready), .m_data(m_data), .m_last(m_last));

    always #5 clk = ~clk;

    // A = [[1,2,3,4],[5,6,7,8],[-1,-2,-3,-4],[2,0,-2,1]],  B = 2*I with B[0][3] = 1
    // Beat k carries column k of A and row k of B.
    reg [N*8-1:0] a_col [0:3];
    reg [N*8-1:0] b_row [0:3];
    integer k;
    initial begin
        a_col[0] = {8'sd2,  -8'sd1, 8'sd5, 8'sd1};
        a_col[1] = {8'sd0,  -8'sd2, 8'sd6, 8'sd2};
        a_col[2] = {-8'sd2, -8'sd3, 8'sd7, 8'sd3};
        a_col[3] = {8'sd1,  -8'sd4, 8'sd8, 8'sd4};
        b_row[0] = {8'sd1, 8'sd0, 8'sd0, 8'sd2};
        b_row[1] = {8'sd0, 8'sd0, 8'sd2, 8'sd0};
        b_row[2] = {8'sd0, 8'sd2, 8'sd0, 8'sd0};
        b_row[3] = {8'sd2, 8'sd0, 8'sd0, 8'sd0};
        $dumpfile("wave.vcd");
        $dumpvars(0, wave_tb);
        #22 rst_n = 1;
        @(negedge clk) begin start = 1; k_len = 4; end
        @(negedge clk) start = 0;
        for (k = 0; k < 4; k = k + 1) begin
            s_valid = 1; s_a = a_col[k]; s_b = b_row[k];
            @(negedge clk);
        end
        s_valid = 0; s_a = 0; s_b = 0; m_ready = 1;
        wait (done);
        @(negedge clk);
        @(negedge clk);
        $finish;
    end
endmodule
